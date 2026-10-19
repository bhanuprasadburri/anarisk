"""Dashboard aggregates. Every number is computed from the database within the caller's organization scope."""
from __future__ import annotations

import uuid

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.models import CaseEntity, CaseEscalation, CaseEvent, DigitalEntity, InvestigationCase, User
from app.models.enums import CaseStatus, EntityType, Provenance, Severity, UserRole
from app.repositories.access import brand_scope, get_brand_for_user

SENSITIVE_PERMISSIONS = {
    "READ_SMS", "RECEIVE_SMS", "SEND_SMS", "READ_CONTACTS", "READ_CALL_LOG", "RECORD_AUDIO", "CAMERA", "SYSTEM_ALERT_WINDOW",
    "BIND_ACCESSIBILITY_SERVICE", "READ_EXTERNAL_STORAGE", "ACCESS_FINE_LOCATION", "REQUEST_INSTALL_PACKAGES",
}


def _scoped_entities(actor: User, brand_id: uuid.UUID | None, provenance: Provenance | None = None):
    stmt = select(DigitalEntity).where(brand_scope(actor, DigitalEntity.brand_id))
    if brand_id:
        stmt = stmt.where(DigitalEntity.brand_id == brand_id)
    if provenance:
        stmt = stmt.where(DigitalEntity.provenance == provenance)
    return stmt


def _case_scope(actor: User, brand_id):
    conds = [brand_scope(actor, InvestigationCase.brand_id)]
    if brand_id:
        conds.append(InvestigationCase.brand_id == brand_id)
    if actor.role == UserRole.PARTNER:
        conds.append(exists().where(CaseEscalation.case_id == InvestigationCase.id))
    return and_(*conds)


def _entity_row(e: DigitalEntity) -> dict:
    return {"id": str(e.id), "entity_type": e.entity_type.value, "display_name": e.display_name, "brand_id": str(e.brand_id),
            "risk_score": e.current_risk_score, "confidence": e.current_confidence, "severity": e.current_severity.value,
            "provenance": e.provenance.value, "last_assessed_at": e.last_assessed_at, "first_seen_at": e.first_seen_at}


def stats(db: Session, actor: User, brand_id: uuid.UUID | None = None, provenance: Provenance | None = None) -> dict:
    if brand_id:
        get_brand_for_user(db, actor, brand_id)
    ent = _scoped_entities(actor, brand_id, provenance).subquery()
    total = db.scalar(select(func.count()).select_from(ent)) or 0
    by_sev = dict(db.execute(select(ent.c.current_severity, func.count()).group_by(ent.c.current_severity)).all())
    by_type = dict(db.execute(select(ent.c.entity_type, func.count()).group_by(ent.c.entity_type)).all())
    by_prov = dict(db.execute(select(ent.c.provenance, func.count()).group_by(ent.c.provenance)).all())
    high = sum(by_sev.get(s.value, 0) for s in (Severity.HIGH, Severity.CRITICAL))
    cscope = _case_scope(actor, brand_id)
    by_status = dict(db.execute(select(InvestigationCase.status, func.count()).where(cscope).group_by(InvestigationCase.status)).all())
    open_cases = sum(v for k, v in by_status.items() if k != CaseStatus.RESOLVED.value)
    unassigned_open = db.scalar(select(func.count()).select_from(InvestigationCase).where(
        cscope, InvestigationCase.status != CaseStatus.RESOLVED, InvestigationCase.assigned_to_id.is_(None))) or 0
    recent = db.scalars(_scoped_entities(actor, brand_id, provenance).where(DigitalEntity.last_assessed_at.is_not(None))
                        .order_by(DigitalEntity.last_assessed_at.desc()).limit(10)).all()
    top = db.scalars(_scoped_entities(actor, brand_id, provenance).where(DigitalEntity.current_risk_score.is_not(None))
                     .order_by(DigitalEntity.current_risk_score.desc()).limit(10)).all()
    activity = db.execute(
        select(CaseEvent, InvestigationCase.case_number, InvestigationCase.title).join(InvestigationCase, InvestigationCase.id == CaseEvent.case_id)
        .where(cscope).order_by(CaseEvent.created_at.desc()).limit(15)).all()
    return {
        "totals": {"monitored_entities": total, "high_risk_entities": high, "unassessed_entities": by_sev.get("unknown", 0),
                   "open_cases": open_cases, "escalated_cases": by_status.get("escalated", 0), "unassigned_open_cases": unassigned_open,
                   "resolved_cases": by_status.get("resolved", 0)},
        "risk_distribution": {s.value: by_sev.get(s.value, 0) for s in Severity},
        "entity_type_distribution": {t.value: by_type.get(t.value, 0) for t in EntityType},
        "data_provenance": {p.value: by_prov.get(p.value, 0) for p in Provenance},
        "case_status_distribution": {s.value: by_status.get(s.value, 0) for s in CaseStatus},
        "recent_detections": [_entity_row(e) for e in recent],
        "top_risk_entities": [_entity_row(e) for e in top],
        "latest_activity": [{"case_id": str(ev.case_id), "case_number": num, "case_title": title, "event_type": ev.event_type.value,
                             "from_status": ev.from_status.value if ev.from_status else None, "to_status": ev.to_status.value if ev.to_status else None,
                             "actor_id": str(ev.actor_id) if ev.actor_id else None, "created_at": ev.created_at} for ev, num, title in activity],
    }


def mobile_apps(db: Session, actor: User, brand_id: uuid.UUID | None = None, limit: int = 25) -> dict:
    if brand_id:
        get_brand_for_user(db, actor, brand_id)
    base = _scoped_entities(actor, brand_id).where(DigitalEntity.entity_type == EntityType.MOBILE_APP)
    apps = db.scalars(base.order_by(DigitalEntity.current_risk_score.desc().nulls_last(), DigitalEntity.last_seen_at.desc())).all()
    by_sev = {s.value: 0 for s in Severity}
    rows = []
    case_counts = dict(db.execute(select(CaseEntity.entity_id, func.count()).where(CaseEntity.entity_id.in_([a.id for a in apps] or [uuid.uuid4()])).group_by(CaseEntity.entity_id)).all())
    for a in apps:
        by_sev[a.current_severity.value] += 1
        at = a.attributes or {}
        perms = at.get("permissions")
        if perms is None:
            status = "not_provided"
        elif a.provenance == Provenance.COLLECTED and at.get("permissions_source") == "store_listing":
            status = "collected_from_store_listing"
        else:
            status = "supplied_unverified"  # we never claim verification for manual / synthetic input
        rows.append({
            **_entity_row(a), "app_name": at.get("app_name"), "package_id": at.get("package_id"), "store": at.get("store"),
            "publisher_name": at.get("publisher_name"), "publisher_verified": False, "store_url": at.get("store_url"),
            "permissions_status": status, "permissions_count": len(perms) if perms else 0,
            "sensitive_permissions": sorted(set(perms or []) & SENSITIVE_PERMISSIONS), "linked_websites": at.get("linked_websites", []),
            "cases": case_counts.get(a.id, 0),
        })
    return {"total_apps": len(apps), "by_severity": by_sev, "high_risk_apps": by_sev["high"] + by_sev["critical"],
            "apps_with_cases": sum(1 for r in rows if r["cases"]), "apps": rows[:limit],
            "note": "publisher_verified is always false: publisher identity is never verified by this platform"}
