"""On-demand investigation tools.

Each tool runs deterministic, evidence-backed checks and persists a :class:`ToolAnalysis`.
Official context (brand names, domains, handles) always comes from the *user's own
organization* brand references (admins see every brand), so cross-tenant data never leaks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailure
from app.models import Brand, BrandReference, ToolAnalysis, User
from app.models.enums import ReferenceKind
from app.services.tools.common import Finding, compute_overall, sanitize_input, METHODOLOGY_VERSION
from app.services.tools.email_analyzer import analyze_email, parse_eml
from app.services.tools.image_analyzer import analyze_image, embedded_software_tag, run_ai_review
from app.services.tools.job_analyzer import analyze_job_offer
from app.services.tools.social_analyzer import analyze_social_profile
from app.services.tools.url_analyzer import analyze_url
from app.utils.images import inspect_image, perceptual_hash, sha256_hex

log = logging.getLogger(__name__)

MAX_PASTED_EMAIL_BYTES = 1 * 1024 * 1024


@dataclass
class OfficialContext:
    brand_names: list[str]
    domains: list[str]
    handles: list[dict[str, str]]  # [{"value": "@acme", "platform": "instagram", "brand": "Acme"}]
    image_hashes: list[dict[str, str]] = field(default_factory=list)  # [{"phash": "a1b2…", "brand": "Acme"}]


def load_official_context(db: Session, user: User) -> OfficialContext:
    stmt = select(BrandReference, Brand).join(Brand, BrandReference.brand_id == Brand.id)
    if user.role.value != "administrator":
        if user.organization_id is None:
            return OfficialContext([], [], [])
        stmt = stmt.where(Brand.organization_id == user.organization_id)
    rows = db.execute(stmt).all()
    names: list[str] = []
    domains: list[str] = []
    handles: list[dict[str, str]] = []
    image_hashes: list[dict[str, str]] = []
    for ref, brand in rows:
        if not brand.is_active:
            continue
        if ref.kind == ReferenceKind.NAME and ref.value not in names:
            names.append(ref.value)
        elif ref.kind == ReferenceKind.DOMAIN and ref.value not in domains:
            domains.append(ref.value)
        elif ref.kind == ReferenceKind.HANDLE:
            handles.append({"value": ref.value, "platform": ref.platform or "", "brand": brand.name})
        elif ref.kind == ReferenceKind.IMAGE and ref.perceptual_hash:
            image_hashes.append({"phash": ref.perceptual_hash, "brand": brand.name})
    return OfficialContext(names, domains, handles, image_hashes)


def _persist(
    db: Session, user: User, tool: str, subject: str, input_summary: dict[str, Any],
    findings: list[Finding],
) -> ToolAnalysis:
    risk, severity, confidence = compute_overall(findings)
    row = ToolAnalysis(
        organization_id=user.organization_id,
        created_by_id=user.id,
        tool=tool,
        subject=subject[:255],
        input_summary=sanitize_input(input_summary),
        findings=[f.to_dict() for f in findings],
        risk_score=risk,
        severity=severity,
        confidence=confidence,
        methodology_version=METHODOLOGY_VERSION,
    )
    db.add(row)
    db.commit()
    return row


def run_email_analysis(db: Session, user: User, payload: dict[str, Any]) -> ToolAnalysis:
    if payload.get("raw_email"):
        raw = payload["raw_email"]
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "replace")
        if len(raw) > MAX_PASTED_EMAIL_BYTES:
            raise ValidationFailure("The submitted email exceeds the 1 MB limit.")
        try:
            parsed = parse_eml(raw)
        except ValueError as exc:
            raise ValidationFailure(str(exc))
        parsed["claimed_brand"] = payload.get("claimed_brand") or ""
        parsed["claimed_domain"] = payload.get("claimed_domain") or ""
        payload = parsed
    ctx = load_official_context(db, user)
    subject, findings = analyze_email(payload, ctx.domains, ctx.handles, ctx.brand_names)
    return _persist(db, user, "email", subject, payload, findings)


def run_job_analysis(db: Session, user: User, payload: dict[str, Any]) -> ToolAnalysis:
    ctx = load_official_context(db, user)
    subject, findings = analyze_job_offer(payload, ctx.domains, ctx.brand_names)
    return _persist(db, user, "job_offer", subject, payload, findings)


def run_social_analysis(db: Session, user: User, payload: dict[str, Any]) -> ToolAnalysis:
    ctx = load_official_context(db, user)
    subject, findings = analyze_social_profile(payload, ctx.handles, ctx.domains, ctx.brand_names)
    return _persist(db, user, "social_profile", subject, payload, findings)


def run_url_analysis(db: Session, user: User, payload: dict[str, Any]) -> ToolAnalysis:
    ctx = load_official_context(db, user)
    subject, findings = analyze_url(payload, ctx.domains)
    row = _persist(db, user, "url", subject, payload, findings)
    return row


def run_image_analysis(db: Session, user: User, *, data: bytes, filename: str, context: str) -> ToolAnalysis:
    """Validate an uploaded image by content, run offline checks + optional AI review, persist."""
    meta = inspect_image(data)  # raises ValidationFailure (422/413) for non-images or oversized files
    sha = sha256_hex(data)
    try:
        phash = perceptual_hash(data)
    except Exception:
        phash = ""  # reported honestly as unable_to_verify by the analyzer
    software = embedded_software_tag(data)
    ctx = load_official_context(db, user)
    subject, findings = analyze_image(
        sha256=sha, phash=phash, meta=meta, size_bytes=len(data), context=context,
        image_hashes=ctx.image_hashes, software=software,
    )
    findings += run_ai_review(data=data, mime=meta["content_type"], context=context)
    payload = {
        "context": context, "filename": filename, "format": meta["format"],
        "width": meta["width"], "height": meta["height"], "size_bytes": len(data),
        "sha256": sha, "perceptual_hash": phash,
    }
    return _persist(db, user, "image", subject, payload, findings)


def get_analysis(db: Session, user: User, analysis_id) -> ToolAnalysis:
    row = db.get(ToolAnalysis, analysis_id)
    if row is None or not _in_scope(user, row):
        raise NotFoundError("Analysis not found")
    return row


def list_analyses(db: Session, user: User, *, tool: str | None = None, page: int = 1, page_size: int = 25) -> dict:
    from sqlalchemy import func

    stmt = select(ToolAnalysis)
    count_stmt = select(func.count()).select_from(ToolAnalysis)
    if user.role.value != "administrator":
        stmt = stmt.where(ToolAnalysis.organization_id == user.organization_id)
        count_stmt = count_stmt.where(ToolAnalysis.organization_id == user.organization_id)
    if tool:
        stmt = stmt.where(ToolAnalysis.tool == tool)
        count_stmt = count_stmt.where(ToolAnalysis.tool == tool)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(ToolAnalysis.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _in_scope(user: User, row: ToolAnalysis) -> bool:
    if user.role.value == "administrator":
        return True
    return row.organization_id is not None and row.organization_id == user.organization_id
