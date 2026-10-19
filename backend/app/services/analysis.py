"""Runs the four detection families for an entity, scores them, and persists the immutable results."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.models import CollectionRecord, DetectionSignal, DigitalEntity, RiskAssessment, User
from app.models.enums import Provenance, Severity, SignalStatus, SignalType
from app.repositories.access import brand_scope, get_entity_for_user
from app.schemas.detection import DetectionEntityRef, DetectionItem, SignalSummary
from app.services import audit
from app.services.detection import DETECTORS, DetectionContext, SignalResult
from app.services.official import is_official_asset
from app.services.scoring import compute_score

log = logging.getLogger(__name__)
MAX_PEERS = 500


def build_context(db: Session, entity: DigitalEntity, now: datetime | None = None) -> DetectionContext:
    s = get_settings()
    brand = entity.brand
    peers = db.scalars(
        select(DigitalEntity).where(DigitalEntity.brand_id == entity.brand_id, DigitalEntity.id != entity.id)
        .order_by(DigitalEntity.last_seen_at.desc()).limit(MAX_PEERS)
    ).all()
    count = db.scalar(select(func.count()).select_from(CollectionRecord).where(CollectionRecord.entity_id == entity.id)) or 0
    return DetectionContext(entity=entity, brand=brand, references=list(brand.references), evidence=list(entity.evidence), peers=list(peers),
                            collection_count=count, settings=s, now=now or datetime.now(UTC))


def run_detectors(ctx: DetectionContext) -> list[SignalResult]:
    results = []
    for det in DETECTORS:
        try:
            results.append(det.run(ctx))
        except Exception as exc:  # a broken detector must not take down the analysis; it is reported as FAILED
            log.exception("detector %s failed", det.signal_type.value)
            results.append(SignalResult.failed(det.signal_type, f"{type(exc).__name__}"))
    return results


def analyze_entity(db: Session, actor: User | None, entity: DigitalEntity, *, now: datetime | None = None, commit: bool = True) -> RiskAssessment:
    reason = is_official_asset(entity, entity.brand.references)
    if reason:
        raise ConflictError(f"Analysis skipped: {reason}. Official assets are not scored as threats.", code="official_asset")
    s = get_settings()
    ctx = build_context(db, entity, now)
    results = run_detectors(ctx)
    comp = compute_score(results, entity.provenance, s)
    assessment = RiskAssessment(
        entity_id=entity.id, model_version=s.scoring_model_version, configured_weights=comp.configured_weights,
        effective_weights=comp.effective_weights, component_scores=comp.component_scores, risk_score=comp.risk_score,
        confidence_score=comp.confidence, confidence_breakdown=comp.confidence_breakdown, severity=comp.severity,
        thresholds=comp.thresholds, is_synthetic=entity.provenance == Provenance.SYNTHETIC, notes=comp.notes,
        assessed_at=ctx.now, triggered_by_id=actor.id if actor else None,
    )
    db.add(assessment)
    db.flush()
    for r in results:
        db.add(DetectionSignal(
            entity_id=entity.id, assessment_id=assessment.id, signal_type=r.signal_type, status=r.status, score=r.score,
            explanation=r.explanation, evidence_refs=r.evidence_refs, meta=r.metadata, created_at=ctx.now,
        ))
    entity.current_risk_score = comp.risk_score
    entity.current_confidence = comp.confidence
    entity.current_severity = comp.severity
    entity.last_assessed_at = ctx.now
    db.flush()
    if comp.severity in (Severity.HIGH, Severity.CRITICAL):
        from app.services import notifications as notify_svc

        notify_svc.notify_high_risk(db, entity, assessment)  # best-effort, deduped per entity/24h
    audit.record(db, actor, "entity.analyze", "entity", entity.id,
                 details={"assessment_id": str(assessment.id), "risk_score": comp.risk_score, "severity": comp.severity.value, "confidence": comp.confidence},
                 organization_id=entity.brand.organization_id)
    if commit:
        db.commit()
    db.refresh(assessment)
    return assessment


def analyze_many(db: Session, actor: User, entity_ids: list[uuid.UUID] | None, brand_id: uuid.UUID | None):
    from app.repositories.access import get_brand_for_user

    stmt = select(DigitalEntity).where(brand_scope(actor, DigitalEntity.brand_id))
    if entity_ids:
        stmt = stmt.where(DigitalEntity.id.in_(entity_ids))
    elif brand_id:
        get_brand_for_user(db, actor, brand_id)
        stmt = stmt.where(DigitalEntity.brand_id == brand_id)
    else:
        raise ConflictError("Provide entity_ids or brand_id", code="missing_scope", status_code=422)
    entities = db.scalars(stmt.limit(200)).all()
    found = {e.id for e in entities}
    skipped = [{"entity_id": str(i), "reason": "not found"} for i in (entity_ids or []) if i not in found]
    assessments = []
    for e in entities:
        try:
            assessments.append(analyze_entity(db, actor, e))
        except ConflictError as exc:
            db.rollback()
            skipped.append({"entity_id": str(e.id), "reason": exc.message})
    return assessments, skipped


def latest_assessment(db: Session, entity_id: uuid.UUID) -> RiskAssessment | None:
    return db.scalar(
        select(RiskAssessment).where(RiskAssessment.entity_id == entity_id).options(selectinload(RiskAssessment.signals))
        .order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.id).limit(1)
    )


def list_assessments(db: Session, actor: User, entity_id: uuid.UUID, page: int, page_size: int):
    get_entity_for_user(db, actor, entity_id)
    base = select(RiskAssessment).where(RiskAssessment.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.options(selectinload(RiskAssessment.signals)).order_by(RiskAssessment.assessed_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


def get_assessment(db: Session, actor: User, assessment_id: uuid.UUID) -> RiskAssessment:
    a = db.scalar(select(RiskAssessment).where(RiskAssessment.id == assessment_id).options(selectinload(RiskAssessment.signals)))
    if a is None:
        raise NotFoundError("Assessment not found")
    get_entity_for_user(db, actor, a.entity_id)
    return a


def list_signals(db: Session, actor: User, page: int, page_size: int, entity_id: uuid.UUID | None, signal_type: SignalType | None, status=None, latest_only: bool = True):
    stmt = (select(DetectionSignal, DigitalEntity)
            .join(DigitalEntity, DigitalEntity.id == DetectionSignal.entity_id)
            .where(brand_scope(actor, DigitalEntity.brand_id)))
    if entity_id:
        stmt = stmt.where(DetectionSignal.entity_id == entity_id)
    if signal_type:
        stmt = stmt.where(DetectionSignal.signal_type == signal_type)
    if status:
        stmt = stmt.where(DetectionSignal.status == status)
    if latest_only:
        # only signals from each entity's most recent assessment
        latest = select(RiskAssessment.entity_id, func.max(RiskAssessment.assessed_at).label("t")).group_by(RiskAssessment.entity_id).subquery()
        stmt = stmt.join(RiskAssessment, RiskAssessment.id == DetectionSignal.assessment_id).join(
            latest, (latest.c.entity_id == RiskAssessment.entity_id) & (latest.c.t == RiskAssessment.assessed_at))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(DetectionSignal.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return [(sig, ent) for sig, ent in rows], total


# ---------- detections feed (latest assessment per entity) ----------
SIGNAL_LABELS = {
    SignalType.BRAND_LOGO: "Visual brand impersonation",
    SignalType.IMPERSONATION: "Identity impersonation",
    SignalType.URL_RISK: "Suspicious URL / infrastructure",
    SignalType.BEHAVIOR: "Inauthentic account behaviour",
}

DETECTION_SORTS = {"risk_score": RiskAssessment.risk_score, "confidence": RiskAssessment.confidence_score,
                   "assessed_at": RiskAssessment.assessed_at}


def _detection_status(signals) -> str:
    """analyzed = all four families ran; partial = some ran; unavailable = none ran (NOT 'low risk')."""
    ok = sum(1 for s in signals if s.status == SignalStatus.OK)
    if ok == len(SignalType):
        return "analyzed"
    return "partial" if ok else "unavailable"


def to_detection_item(assessment: RiskAssessment, entity: DigitalEntity) -> DetectionItem:
    signals = list(assessment.signals or [])
    by_type = {s.signal_type: s for s in signals}
    eff = assessment.effective_weights or {}
    # detection type = highest effective weight signal that actually produced a score, else the highest-weight family overall
    scored = [s for s in signals if s.status == SignalStatus.OK and s.score is not None]
    primary = max(scored or signals, key=lambda s: (eff.get(s.signal_type.value, 0.0), s.score or 0.0), default=None)
    return DetectionItem(
        id=assessment.id,
        entity=DetectionEntityRef(id=entity.id, display_name=entity.display_name, entity_type=entity.entity_type.value,
                                  canonical_id=entity.canonical_id, platform=entity.platform, provenance=entity.provenance.value),
        detection_type=SIGNAL_LABELS.get(primary.signal_type, primary.signal_type.value) if primary else "No signal available",
        signal_type=primary.signal_type if primary else None,
        risk_score=assessment.risk_score,
        confidence=assessment.confidence_score,
        severity=assessment.severity,
        status=_detection_status(signals),
        explanation=primary.explanation if primary else (assessment.notes or ""),
        signals_summary=[SignalSummary(signal_type=s.signal_type, status=s.status, score=s.score) for s in signals],
        assessed_at=assessment.assessed_at,
        is_synthetic=assessment.is_synthetic,
    )


def list_detections(
    db: Session, actor: User, *, page: int, page_size: int, q: str | None = None, severity: Severity | None = None,
    entity_type=None, brand_id: uuid.UUID | None = None, status: str | None = None, provenance: Provenance | None = None,
    date_from: datetime | None = None, date_to: datetime | None = None, sort: str = "assessed_at", order: str = "desc",
) -> tuple[list[DetectionItem], int]:
    """Flattened latest-assessment-per-entity feed with the filters the Detections page exposes."""
    rn = func.row_number().over(partition_by=RiskAssessment.entity_id,
                                order_by=[RiskAssessment.assessed_at.desc(), RiskAssessment.id.desc()]).label("rn")
    latest = select(RiskAssessment.id, rn).subquery()
    ok_count = (select(func.count()).select_from(DetectionSignal)
                .where(DetectionSignal.assessment_id == RiskAssessment.id, DetectionSignal.status == SignalStatus.OK)
                .correlate(RiskAssessment).scalar_subquery())
    stmt = (select(RiskAssessment, DigitalEntity)
            .join(latest, latest.c.id == RiskAssessment.id)
            .join(DigitalEntity, DigitalEntity.id == RiskAssessment.entity_id)
            .where(latest.c.rn == 1, brand_scope(actor, DigitalEntity.brand_id)))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(DigitalEntity.display_name.ilike(like), DigitalEntity.canonical_id.ilike(like)))
    if severity:
        stmt = stmt.where(RiskAssessment.severity == severity)
    if entity_type:
        stmt = stmt.where(DigitalEntity.entity_type == entity_type)
    if brand_id:
        stmt = stmt.where(DigitalEntity.brand_id == brand_id)
    if provenance:
        stmt = stmt.where(DigitalEntity.provenance == provenance)
    if date_from:
        stmt = stmt.where(RiskAssessment.assessed_at >= date_from)
    if date_to:
        stmt = stmt.where(RiskAssessment.assessed_at <= date_to)
    if status == "analyzed":
        stmt = stmt.where(ok_count == len(SignalType))
    elif status == "partial":
        stmt = stmt.where(ok_count.between(1, len(SignalType) - 1))
    elif status == "unavailable":
        stmt = stmt.where(ok_count == 0)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    col = DETECTION_SORTS.get(sort, RiskAssessment.assessed_at)
    col = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.execute(stmt.options(selectinload(RiskAssessment.signals))
                      .order_by(col, RiskAssessment.id).offset((page - 1) * page_size).limit(page_size)).all()
    return [to_detection_item(a, e) for a, e in rows], total
