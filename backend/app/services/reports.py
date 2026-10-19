"""Aggregate reports. Every number is computed from the database; nothing is hard-coded.

Date-range semantics (documented in `data_notes` of the response): detections, evidence counts and the
risk trend respect the selected range; totals/distributions/channels are point-in-time snapshots.
Empty databases return zeros and empty arrays - never an error.
"""
from __future__ import annotations


def _csv_safe(value):
    """Prevent spreadsheet formula execution for untrusted exported values."""
    if isinstance(value, str) and value.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value

import csv
import io
import uuid
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailure
from app.models import (
    CaseEscalation, DigitalEntity, EntityRelationship, EvidenceRecord,
    InvestigationCase, MonitoringTarget, RiskAssessment,
)
from app.models.enums import CaseStatus, EntityType, Provenance, Severity, UserRole
from app.repositories.access import brand_scope, get_brand_for_user

MAX_RANGE_DAYS = 366

CSV_COLUMNS: dict[str, list[str]] = {
    "threats": ["entity", "type", "risk", "confidence", "severity", "assessed_at"],
    "cases": ["case_number", "title", "brand", "severity", "status", "assignee", "created", "updated"],
    "entities": ["name", "canonical_id", "type", "platform", "severity", "risk", "provenance", "last_seen"],
    "apps": ["app_name", "package_id", "store", "publisher", "risk", "severity", "last_seen"],
    "evidence": ["id", "kind", "file_name", "entity", "sha256", "size", "verification_status", "created_at"],
}


def parse_range(from_: str | None, to: str | None) -> tuple[date, date]:
    try:
        d_to = date.fromisoformat(to) if to else date.today()
        d_from = date.fromisoformat(from_) if from_ else d_to - timedelta(days=30)
    except ValueError:
        raise ValidationFailure("from/to must be ISO dates (yyyy-mm-dd)", details=[{"field": "from", "message": "invalid date"}])
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > MAX_RANGE_DAYS:
        raise ValidationFailure(f"Date range too large (max {MAX_RANGE_DAYS} days)")
    return d_from, d_to


def _bounds(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    return (datetime.combine(d_from, time.min, tzinfo=UTC),
            datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=UTC))


def _case_scope(actor, brand_id):
    conds = [brand_scope(actor, InvestigationCase.brand_id)]
    if brand_id:
        conds.append(InvestigationCase.brand_id == brand_id)
    if actor.role == UserRole.PARTNER:
        conds.append(exists().where(CaseEscalation.case_id == InvestigationCase.id))
    return and_(*conds)


def _entity_stmt(actor, brand_id, provenance: Provenance | None = None):
    stmt = select(DigitalEntity).where(brand_scope(actor, DigitalEntity.brand_id))
    if brand_id:
        stmt = stmt.where(DigitalEntity.brand_id == brand_id)
    if provenance:
        stmt = stmt.where(DigitalEntity.provenance == provenance)
    return stmt


def _verification_status(ev: EvidenceRecord) -> str:
    try:
        from app.services.evidence import verification_status

        return verification_status(ev)
    except ImportError:
        # services/evidence.py is owned by another workstream and may not expose the
        # helper yet; report honestly instead of crashing or fabricating "verified".
        meta = ev.meta or {}
        explicit = meta.get("verification_status") or meta.get("verification")
        if explicit in ("verified", "mismatch", "pending"):
            return explicit
        if ev.sha256 and meta.get("stored_sha256") and meta["stored_sha256"] == ev.sha256:
            return "verified"
        if ev.sha256 and meta.get("stored_sha256"):
            return "mismatch"
        return "pending"


def overview(db: Session, actor, from_: str | None, to: str | None, brand_id: uuid.UUID | None,
             provenance: Provenance | None = None) -> dict:
    if brand_id:
        get_brand_for_user(db, actor, brand_id)
    d_from, d_to = parse_range(from_, to)
    start, end = _bounds(d_from, d_to)

    # ---- entity snapshot ----
    ent = _entity_stmt(actor, brand_id, provenance)
    entities = db.scalars(ent).all()
    by_type = Counter(e.entity_type.value for e in entities)
    by_sev = Counter(e.current_severity.value for e in entities)

    # ---- cases (current state) ----
    case_scope = _case_scope(actor, brand_id)
    by_status = {s.value: 0 for s in CaseStatus}
    for status, n in db.execute(select(InvestigationCase.status, func.count()).where(case_scope).group_by(InvestigationCase.status)):
        by_status[status.value] = n

    # ---- detections within the date range ----
    det_stmt = (
        select(func.count(RiskAssessment.id))
        .join(DigitalEntity, DigitalEntity.id == RiskAssessment.entity_id)
        .where(brand_scope(actor, DigitalEntity.brand_id), RiskAssessment.assessed_at >= start, RiskAssessment.assessed_at < end)
    )
    if brand_id:
        det_stmt = det_stmt.where(DigitalEntity.brand_id == brand_id)
    if provenance:
        det_stmt = det_stmt.where(DigitalEntity.provenance == provenance)
    detections = db.scalar(det_stmt) or 0

    trend_stmt = (
        select(func.date(RiskAssessment.assessed_at).label("d"), func.avg(RiskAssessment.risk_score), func.count(RiskAssessment.id))
        .join(DigitalEntity, DigitalEntity.id == RiskAssessment.entity_id)
        .where(brand_scope(actor, DigitalEntity.brand_id), RiskAssessment.assessed_at >= start, RiskAssessment.assessed_at < end)
    )
    if brand_id:
        trend_stmt = trend_stmt.where(DigitalEntity.brand_id == brand_id)
    if provenance:
        trend_stmt = trend_stmt.where(DigitalEntity.provenance == provenance)
    trend_rows = db.execute(trend_stmt.group_by("d")).all()
    trend_map = {r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]): (float(r[1]) if r[1] is not None else None, r[2])
                 for r in trend_rows}
    risk_trend = []
    day = d_from
    while day <= d_to:
        avg, n = trend_map.get(day.isoformat(), (None, 0))
        risk_trend.append({"date": day.isoformat(), "avg_risk": round(avg, 4) if avg is not None else None, "detections": n})
        day += timedelta(days=1)

    # ---- evidence within the date range ----
    ev_stmt = select(EvidenceRecord).where(brand_scope(actor, EvidenceRecord.brand_id),
                                           EvidenceRecord.created_at >= start, EvidenceRecord.created_at < end)
    if brand_id:
        ev_stmt = ev_stmt.where(EvidenceRecord.brand_id == brand_id)
    if provenance:
        ev_stmt = ev_stmt.where(EvidenceRecord.provenance == provenance)
    ev_rows = db.scalars(ev_stmt).all()
    ev_status = Counter(_verification_status(e) for e in ev_rows)
    ev_kind = Counter(e.kind.value for e in ev_rows)

    # ---- relationships / top connected ----
    ent_ids = [e.id for e in entities]
    counts: Counter = Counter()
    if ent_ids:
        for s, t in db.execute(select(EntityRelationship.source_entity_id, EntityRelationship.target_entity_id)
                               .where(EntityRelationship.source_entity_id.in_(ent_ids),
                                      EntityRelationship.target_entity_id.in_(ent_ids))):
            counts[s] += 1
            counts[t] += 1
    top = []
    if counts:
        by_id = {e.id: e for e in entities}
        for eid, n in counts.most_common(10):
            e = by_id.get(eid)
            if e:
                top.append({"entity_id": e.id, "display_name": e.display_name, "entity_type": e.entity_type.value,
                            "risk_score": e.current_risk_score, "relationship_count": n})

    # ---- channels: entities AT RISK (severity high/critical) per product channel ----
    CHANNEL_OF = {
        EntityType.SOCIAL_PROFILE: "Social",
        EntityType.WEBSITE: "Web",
        EntityType.DOMAIN: "Web",
        EntityType.MOBILE_APP: "App",
        EntityType.IMAGE: "Image",
    }
    channels: Counter = Counter()
    for e in entities:
        if e.current_severity in (Severity.HIGH, Severity.CRITICAL):
            channels[CHANNEL_OF.get(e.entity_type, "Other")] += 1
    threats_by_channel = [
        {"channel": name, "count": channels.get(name, 0)}
        for name in ("Social", "Web", "App", "Image", "Other")
    ]

    # ---- severity by type ----
    sev_grid = Counter((e.entity_type.value, e.current_severity.value) for e in entities)
    severity_by_type = [
        {"entity_type": t.value, **{s.value: sev_grid.get((t.value, s.value), 0) for s in Severity}}
        for t in EntityType
    ]

    # ---- mobile apps ----
    apps = [e for e in entities if e.entity_type == EntityType.MOBILE_APP]
    by_store = Counter(a.platform or "unknown" for a in apps)
    app_high = sum(1 for a in apps if a.current_severity in (Severity.HIGH, Severity.CRITICAL))

    # ---- relationships total ----
    rel_total = 0
    if ent_ids:
        rel_total = db.scalar(select(func.count()).select_from(EntityRelationship).where(
            EntityRelationship.source_entity_id.in_(ent_ids), EntityRelationship.target_entity_id.in_(ent_ids))) or 0

    open_cases = sum(v for k, v in by_status.items() if k != CaseStatus.RESOLVED.value)
    data_notes = [
        "Risk scores are produced by an explainable rule-based heuristic (model from config) and require human review.",
        "Some records are synthetic demo data (provenance=synthetic) and are not live threats.",
        "risk_trend.avg_risk is the mean of all risk assessments taken on that day (assessed_at day bucket); "
        "days without assessments are null with 0 detections.",
        "threats_by_channel counts ONLY high/critical-risk entities ('entities at risk') per product channel.",
        "Totals, distributions and channels are point-in-time snapshots; detections, evidence counts and the "
        "risk trend respect the selected date range.",
        "When a purpose (provenance) filter is active, entity, detection, evidence, relationship and app summaries "
        "use that provenance. Case workflow counts remain scope-wide because cases do not have a provenance field.",
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "date_range": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "totals": {
            "entities": len(entities),
            "high_risk": by_sev.get(Severity.HIGH.value, 0),
            "critical": by_sev.get(Severity.CRITICAL.value, 0),
            "open_cases": open_cases,
            "escalated_cases": by_status.get(CaseStatus.ESCALATED.value, 0),
            "resolved_cases": by_status.get(CaseStatus.RESOLVED.value, 0),
            "detections": detections,
            "evidence": len(ev_rows),
            "relationships": rel_total,
        },
        "threat_distribution": {s.value: by_sev.get(s.value, 0) for s in Severity},
        "cases_by_status": by_status,
        "risk_trend": risk_trend,
        "threats_by_channel": threats_by_channel,
        "top_connected_entities": top,
        "entity_type_distribution": {t.value: by_type.get(t.value, 0) for t in EntityType},
        "severity_by_type": severity_by_type,
        "mobile_apps": {"total": len(apps), "high_risk": app_high,
                        "by_store": [{"store": s, "count": n} for s, n in by_store.most_common()]},
        "evidence": {"total": len(ev_rows), "verified": ev_status.get("verified", 0),
                     "pending": ev_status.get("pending", 0) + ev_status.get("mismatch", 0),
                     "mismatch": ev_status.get("mismatch", 0),
                     "by_kind": [{"kind": k, "count": n} for k, n in sorted(ev_kind.items())]},
        "data_notes": data_notes,
    }


# ---------- CSV export ----------
def _iso(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (Severity, CaseStatus, EntityType)) or hasattr(v, "value"):
        return getattr(v, "value", str(v))
    return v


def export_csv(db: Session, actor, report: str, from_: str | None, to: str | None, brand_id: uuid.UUID | None,
               provenance: Provenance | None = None) -> tuple[str, str]:
    if report not in CSV_COLUMNS:
        raise ValidationFailure(
            f"Unknown report '{report}'. Valid reports: {', '.join(sorted(CSV_COLUMNS))}. "
            "Columns per report: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(CSV_COLUMNS.items())),
            details=[{"field": "report", "message": "must be one of " + ", ".join(sorted(CSV_COLUMNS))}],
        )
    if brand_id:
        get_brand_for_user(db, actor, brand_id)
    d_from, d_to = parse_range(from_, to)
    start, end = _bounds(d_from, d_to)
    columns = CSV_COLUMNS[report]
    rows: list[list] = []

    if report == "threats":
        stmt = (select(RiskAssessment, DigitalEntity)
                .join(DigitalEntity, DigitalEntity.id == RiskAssessment.entity_id)
                .where(brand_scope(actor, DigitalEntity.brand_id),
                       RiskAssessment.assessed_at >= start, RiskAssessment.assessed_at < end)
                .order_by(RiskAssessment.assessed_at.desc()))
        if brand_id:
            stmt = stmt.where(DigitalEntity.brand_id == brand_id)
        if provenance:
            stmt = stmt.where(DigitalEntity.provenance == provenance)
        for a, e in db.execute(stmt):
            rows.append([e.display_name, e.entity_type.value, a.risk_score, a.confidence_score,
                         a.severity.value, a.assessed_at])
    elif report == "cases":
        stmt = (select(InvestigationCase).where(_case_scope(actor, brand_id),
                                                InvestigationCase.created_at >= start, InvestigationCase.created_at < end)
                .order_by(InvestigationCase.created_at.desc()))
        for c in db.scalars(stmt):
            rows.append([c.case_number, c.title, c.brand.name if c.brand else "", c.severity.value,
                         c.status.value, c.assigned_to.email if c.assigned_to else "",
                         c.created_at, c.updated_at])
    elif report == "entities":
        stmt = _entity_stmt(actor, brand_id, provenance).where(
            DigitalEntity.created_at >= start, DigitalEntity.created_at < end).order_by(DigitalEntity.created_at.desc())
        for e in db.scalars(stmt):
            rows.append([e.display_name, e.canonical_id, e.entity_type.value, e.platform,
                         e.current_severity.value, e.current_risk_score, e.provenance.value, e.last_seen_at])
    elif report == "apps":
        stmt = (select(MonitoringTarget)
                .outerjoin(DigitalEntity, DigitalEntity.id == MonitoringTarget.entity_id)
                .where(brand_scope(actor, MonitoringTarget.brand_id),
                       MonitoringTarget.created_at >= start, MonitoringTarget.created_at < end)
                .order_by(MonitoringTarget.created_at.desc()))
        if brand_id:
            stmt = stmt.where(MonitoringTarget.brand_id == brand_id)
        if provenance:
            stmt = stmt.where(DigitalEntity.provenance == provenance)
        for t, e in db.execute(stmt):
            attrs = (e.attributes or {}) if e else {}
            rows.append([attrs.get("app_name", "") or t.package_id, t.package_id, t.store,
                         attrs.get("publisher_name", ""), e.current_risk_score if e else None,
                         e.current_severity.value if e else "unknown",
                         (e.last_seen_at if e else None) or t.last_sync_at])
    else:  # evidence
        stmt = select(EvidenceRecord).where(brand_scope(actor, EvidenceRecord.brand_id),
                                            EvidenceRecord.created_at >= start, EvidenceRecord.created_at < end)
        if brand_id:
            stmt = stmt.where(EvidenceRecord.brand_id == brand_id)
        if provenance:
            stmt = stmt.where(EvidenceRecord.provenance == provenance)
        for ev in db.scalars(stmt.order_by(EvidenceRecord.created_at.desc())):
            rows.append([ev.id, ev.kind.value, (ev.meta or {}).get("original_filename") or "",
                         ev.entity.display_name if ev.entity else "", ev.sha256 or "",
                         ev.size_bytes or "", _verification_status(ev), ev.created_at])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows([[_csv_safe(value) for value in row] for row in rows])
    filename = f"anarisk-{report}-{date.today().isoformat()}.csv"
    return filename, buf.getvalue()
