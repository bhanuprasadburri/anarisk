"""Evidence: creation, image upload (content-validated), verification status, case links, deletion.

Verification status semantics (never fabricated):
  * "mismatch" - a previous /verify recomputed a different sha256 than the stored one (meta.verify_mismatch)
  * "verified" - the record carries a sha256 that was confirmed (upload-time hash, or /verify match)
  * "pending"  - no confirmation yet (e.g. text evidence, or a file never re-verified)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailure
from app.models import CaseEvidenceLink, EvidenceRecord, User
from app.models.enums import EvidenceKind, Provenance, UserRole
from app.repositories.access import brand_scope, get_entity_for_user
from app.schemas.evidence import EvidenceCreate, EvidenceOut, EvidenceVerification
from app.services import audit
from app.utils.images import inspect_image, perceptual_hash, sha256_hex

# SQL expression for the verification status of a row (used by the list filter).
VERIFICATION_SQL = case(
    (func.coalesce(EvidenceRecord.meta["verify_mismatch"].as_boolean(), False), literal("mismatch")),
    (and_(EvidenceRecord.sha256.is_not(None),
          func.coalesce(EvidenceRecord.meta["verified"].as_boolean(), False)), literal("verified")),
    else_=literal("pending"),
)
VERIFICATION_VALUES = ("verified", "mismatch", "pending")


def verification_status(ev: EvidenceRecord) -> str:
    """verified | mismatch | pending - derived strictly from stored facts, never guessed."""
    meta = ev.meta or {}
    if meta.get("verify_mismatch"):
        return "mismatch"
    if ev.sha256 and meta.get("verified"):
        return "verified"
    return "pending"


def create_evidence(db: Session, actor: User, data: EvidenceCreate) -> EvidenceRecord:
    entity = get_entity_for_user(db, actor, data.entity_id)
    sha = hashlib.sha256(data.text_content.encode("utf-8")).hexdigest() if data.text_content else None
    ev = EvidenceRecord(
        entity_id=entity.id, brand_id=entity.brand_id, kind=data.kind, title=data.title, description=data.description,
        source_url=data.source_url, provenance=data.provenance, text_content=data.text_content, sha256=sha,
        meta=data.metadata, collected_at=data.collected_at or datetime.now(UTC), created_by_id=actor.id,
    )
    db.add(ev)
    db.flush()
    audit.record(db, actor, "evidence.create", "evidence", ev.id, details={"entity_id": str(entity.id), "kind": ev.kind.value})
    db.commit()
    return ev


def upload_image_evidence(
    db: Session, actor: User, entity_id: uuid.UUID, data: bytes, *, title: str, description: str | None, kind: EvidenceKind,
    provenance: Provenance, original_filename: str | None,
) -> EvidenceRecord:
    entity = get_entity_for_user(db, actor, entity_id)
    info = inspect_image(data)  # validates real content, size, pixel budget
    sha = sha256_hex(data)
    if db.scalar(select(EvidenceRecord.id).where(EvidenceRecord.entity_id == entity.id, EvidenceRecord.sha256 == sha)):
        raise ConflictError("This file is already attached to the entity as evidence", code="duplicate_evidence")
    rel = Path("evidence") / str(entity.brand_id) / f"{sha}.{info['extension']}"  # name derived from content hash, never the client filename
    dest = Path(get_settings().upload_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)
    safe_name = "".join(c for c in (original_filename or "") if c.isalnum() or c in "._- ")[:120] or None
    ev = EvidenceRecord(
        entity_id=entity.id, brand_id=entity.brand_id, kind=kind, title=title, description=description, provenance=provenance,
        content_type=info["content_type"], file_path=str(rel), sha256=sha, size_bytes=len(data), perceptual_hash=perceptual_hash(data),
        meta={"width": info["width"], "height": info["height"], "format": info["format"], "original_filename": safe_name,
              "verified": True, "verified_at": datetime.now(UTC).isoformat()},
        collected_at=datetime.now(UTC), created_by_id=actor.id,
    )
    db.add(ev)
    db.flush()
    audit.record(db, actor, "evidence.upload", "evidence", ev.id, details={"entity_id": str(entity.id), "sha256": sha, "size": len(data)})
    db.commit()
    return ev


def get_evidence(db: Session, actor: User, evidence_id: uuid.UUID) -> EvidenceRecord:
    ev = db.scalar(select(EvidenceRecord).where(brand_scope(actor, EvidenceRecord.brand_id), EvidenceRecord.id == evidence_id))
    if ev is None:
        raise NotFoundError("Evidence not found")
    return ev


def _scope(actor: User, stmt):
    """Backwards-compatible alias (brand scoping predicate for evidence queries)."""
    return stmt.where(brand_scope(actor, EvidenceRecord.brand_id))


def _filtered(
    db: Session, actor: User, entity_id: uuid.UUID | None = None, kind: EvidenceKind | None = None,
    case_id: uuid.UUID | None = None, verification_status_: str | None = None, q: str | None = None,
):
    """Build the WHERE clause shared by the list endpoint and the CSV export."""
    from app.models import CaseEntity

    stmt = select(EvidenceRecord).where(brand_scope(actor, EvidenceRecord.brand_id))
    if entity_id:
        stmt = stmt.where(EvidenceRecord.entity_id == entity_id)
    if kind:
        stmt = stmt.where(EvidenceRecord.kind == kind)
    if case_id:
        stmt = stmt.where(
            (EvidenceRecord.entity_id.in_(select(CaseEntity.entity_id).where(CaseEntity.case_id == case_id)))
            | (EvidenceRecord.id.in_(select(CaseEvidenceLink.evidence_id).where(CaseEvidenceLink.case_id == case_id)))
        )
    if verification_status_:
        if verification_status_ not in VERIFICATION_VALUES:
            raise ValidationFailure("verification_status must be one of: verified, mismatch, pending")
        stmt = stmt.where(VERIFICATION_SQL == verification_status_)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(EvidenceRecord.title.ilike(like), EvidenceRecord.description.ilike(like),
                              EvidenceRecord.sha256.ilike(like), EvidenceRecord.text_content.ilike(like)))
    return stmt


SORTS = {"created_at": EvidenceRecord.created_at, "collected_at": EvidenceRecord.collected_at,
         "title": EvidenceRecord.title, "size_bytes": EvidenceRecord.size_bytes}


def list_evidence(
    db: Session, actor: User, page: int, page_size: int, entity_id: uuid.UUID | None = None, kind: EvidenceKind | None = None,
    case_id: uuid.UUID | None = None, verification_status_: str | None = None, q: str | None = None,
    sort: str = "created_at", order: str = "desc",
):
    stmt = _filtered(db, actor, entity_id, kind, case_id, verification_status_, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTS.get(sort, EvidenceRecord.created_at)
    col = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.scalars(stmt.options(joinedload(EvidenceRecord.entity))
                      .order_by(col, EvidenceRecord.id).offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


def hydrate(db: Session, rows) -> list[EvidenceOut]:
    """Attach case_ids / file_name / has_file / verification_status / entity to a batch of rows (2 queries)."""
    from app.schemas.evidence import LinkedEntityBrief

    out = [_ev_dict(r) for r in rows]
    ids = [r.id for r in rows]
    by_case: dict[uuid.UUID, list[uuid.UUID]] = {}
    if ids:
        for ev_id, case_id in db.execute(select(CaseEvidenceLink.evidence_id, CaseEvidenceLink.case_id)
                                         .where(CaseEvidenceLink.evidence_id.in_(ids))):
            by_case.setdefault(ev_id, []).append(case_id)
    for o, r in zip(out, rows):
        o["case_ids"] = by_case.get(r.id, [])
        o["entity"] = (LinkedEntityBrief(id=r.entity.id, display_name=r.entity.display_name,
                                         entity_type=r.entity.entity_type.value) if r.entity else None)
    return [EvidenceOut.model_validate(o) for o in out]


def _ev_dict(ev: EvidenceRecord) -> dict:
    return {
        "id": ev.id, "entity_id": ev.entity_id, "brand_id": ev.brand_id, "kind": ev.kind, "title": ev.title,
        "description": ev.description, "source_url": ev.source_url, "provenance": ev.provenance,
        "content_type": ev.content_type, "sha256": ev.sha256, "size_bytes": ev.size_bytes,
        "perceptual_hash": ev.perceptual_hash, "has_file": bool(ev.file_path),
        "file_name": (ev.meta or {}).get("original_filename"), "text_content": ev.text_content, "meta": ev.meta or {},
        "verification_status": verification_status(ev), "case_ids": [], "entity": None,
        "collected_at": ev.collected_at, "created_at": ev.created_at,
    }


def to_out(db: Session, ev: EvidenceRecord) -> EvidenceOut:
    return hydrate(db, [ev])[0]


# ---------- verification ----------
def verify_evidence(db: Session, actor: User, evidence_id: uuid.UUID) -> EvidenceVerification:
    """Recompute the sha256 of the stored bytes (file or text) and record the outcome honestly."""
    ev = get_evidence(db, actor, evidence_id)
    if ev.file_path:
        current = sha256_hex(evidence_file_path(ev).read_bytes())
    elif ev.text_content:
        current = hashlib.sha256(ev.text_content.encode("utf-8")).hexdigest()
    else:
        raise ValidationFailure("This evidence has no re-computable content (no file, no text)")
    matches = current == ev.sha256
    meta = dict(ev.meta or {})
    if matches:
        meta.pop("verify_mismatch", None)
        meta["verified"] = True
    else:
        meta["verify_mismatch"] = True
        meta["verified"] = False
    meta["last_verified_sha256"] = current
    meta["last_verified_at"] = datetime.now(UTC).isoformat()
    ev.meta = meta
    audit.record(db, actor, "evidence.verify", "evidence", ev.id,
                 details={"matches": matches, "stored_sha256": ev.sha256, "recomputed_sha256": current})
    db.commit()
    return EvidenceVerification(sha256=current, stored_sha256=ev.sha256, matches=matches, verified_at=datetime.now(UTC))


# ---------- case links ----------
def link_to_case(db: Session, actor: User, evidence_id: uuid.UUID, case_id: uuid.UUID, role: str = "supporting") -> EvidenceRecord:
    from app.services.cases import get_case_for_user

    ev = get_evidence(db, actor, evidence_id)
    case = get_case_for_user(db, actor, case_id)
    if db.get(CaseEvidenceLink, {"case_id": case.id, "evidence_id": ev.id}):
        raise ConflictError("This evidence is already linked to the case", code="evidence_already_linked")
    db.add(CaseEvidenceLink(case_id=case.id, evidence_id=ev.id, role=role, added_by_id=actor.id))
    audit.record(db, actor, "evidence.link_case", "evidence", ev.id,
                 details={"case_id": str(case.id), "case_number": case.case_number, "role": role},
                 organization_id=case.brand.organization_id)
    db.commit()
    return ev


def unlink_from_case(db: Session, actor: User, evidence_id: uuid.UUID, case_id: uuid.UUID) -> None:
    from app.services.cases import get_case_for_user

    ev = get_evidence(db, actor, evidence_id)
    case = get_case_for_user(db, actor, case_id)
    link = db.get(CaseEvidenceLink, {"case_id": case.id, "evidence_id": ev.id})
    if link is None:
        raise NotFoundError("This evidence is not linked to the case")
    db.delete(link)
    audit.record(db, actor, "evidence.unlink_case", "evidence", ev.id,
                 details={"case_id": str(case.id), "case_number": case.case_number},
                 organization_id=case.brand.organization_id)
    db.commit()


def case_ids_for(db: Session, evidence_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(CaseEvidenceLink.case_id).where(CaseEvidenceLink.evidence_id == evidence_id)))


# ---------- generic links (case and/or entity) ----------
def link_evidence(
    db: Session, actor: User, evidence_id: uuid.UUID, *, case_id: uuid.UUID | None = None, entity_id: uuid.UUID | None = None,
) -> EvidenceRecord:
    """Attach the record to a case (new CaseEvidenceLink, role 'linked') and/or (re)attach it to an entity."""
    from app.services.cases import get_case_for_user

    ev = get_evidence(db, actor, evidence_id)
    details: dict = {}
    if entity_id is not None:
        entity = get_entity_for_user(db, actor, entity_id)
        ev.entity_id, ev.brand_id = entity.id, entity.brand_id  # brand follows the entity (scope is per brand)
        details["entity_id"] = str(entity.id)
    if case_id is not None:
        case = get_case_for_user(db, actor, case_id)
        if not db.get(CaseEvidenceLink, {"case_id": case.id, "evidence_id": ev.id}):
            db.add(CaseEvidenceLink(case_id=case.id, evidence_id=ev.id, role="linked", added_by_id=actor.id))
            db.flush()
        details["case_id"] = str(case.id)
    audit.record(db, actor, "evidence.link", "evidence", ev.id, details=details)
    db.commit()
    return ev


def unlink_evidence(
    db: Session, actor: User, evidence_id: uuid.UUID, *, case_id: uuid.UUID | None = None, entity_id: uuid.UUID | None = None,
) -> None:
    """Remove the case link and/or detach the record from an entity (the record itself is kept)."""
    from app.services.cases import get_case_for_user

    ev = get_evidence(db, actor, evidence_id)
    details: dict = {}
    if case_id is not None:
        get_case_for_user(db, actor, case_id)
        link = db.get(CaseEvidenceLink, {"case_id": case_id, "evidence_id": ev.id})
        if link is not None:
            db.delete(link)
            details["case_id"] = str(case_id)
    if entity_id is not None and ev.entity_id == entity_id:
        get_entity_for_user(db, actor, entity_id)
        ev.entity_id = None  # kept in the brand's evidence pool, no longer attached to that entity
        details["entity_id"] = str(entity_id)
    audit.record(db, actor, "evidence.unlink", "evidence", ev.id, details=details)
    db.commit()


# ---------- deletion ----------
def delete_evidence(db: Session, actor: User, evidence_id: uuid.UUID) -> None:
    """Administrators and investigators only. Removes the stored file, the record and its case links."""
    if actor.role not in (UserRole.ADMIN, UserRole.INVESTIGATOR):
        raise ForbiddenError("Only administrators and investigators may delete evidence")
    ev = get_evidence(db, actor, evidence_id)
    details = {"kind": ev.kind.value, "title": ev.title, "entity_id": str(ev.entity_id), "had_file": bool(ev.file_path)}
    if ev.file_path:
        p = Path(get_settings().upload_dir) / ev.file_path
        try:
            if p.is_file():
                p.unlink()
                details["file_removed"] = True
        except OSError:  # record deletion proceeds; the orphan file is reported in the audit row
            details["file_removed"] = False
    audit.record(db, actor, "evidence.delete", "evidence", ev.id, details=details)
    db.delete(ev)  # case_evidence links cascade in the database
    db.commit()


def evidence_file_path(ev: EvidenceRecord) -> Path:
    if not ev.file_path:
        raise NotFoundError("This evidence record has no file")
    base = Path(get_settings().upload_dir).resolve()
    p = (base / ev.file_path).resolve()
    if base not in p.parents or not p.is_file():  # path-traversal / missing file guard
        raise NotFoundError("Evidence file not found")
    return p


# ---------- CSV export ----------
CSV_COLUMNS = ["id", "kind", "title", "entity", "sha256", "size_bytes", "verification_status", "provenance", "case_ids", "created_at"]


def export_csv(
    db: Session, actor: User, entity_id: uuid.UUID | None = None, kind: EvidenceKind | None = None,
    case_id: uuid.UUID | None = None, verification_status_: str | None = None, q: str | None = None,
) -> tuple[str, str]:
    import csv
    import io

    stmt = _filtered(db, actor, entity_id, kind, case_id, verification_status_, q)
    rows = db.scalars(stmt.options(joinedload(EvidenceRecord.entity)).order_by(EvidenceRecord.created_at.desc())).all()
    by_case: dict[uuid.UUID, list[str]] = {}
    if rows:
        for ev_id, cid in db.execute(select(CaseEvidenceLink.evidence_id, CaseEvidenceLink.case_id)
                                     .where(CaseEvidenceLink.evidence_id.in_([r.id for r in rows]))):
            by_case.setdefault(ev_id, []).append(str(cid))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for ev in rows:
        w.writerow([ev.id, ev.kind.value, ev.title, ev.entity.display_name if ev.entity else "",
                    ev.sha256 or "", ev.size_bytes or "", verification_status(ev), ev.provenance.value,
                    " ".join(by_case.get(ev.id, [])), ev.created_at])
    return f"anarisk-evidence-{datetime.now(UTC).date().isoformat()}.csv", buf.getvalue()
