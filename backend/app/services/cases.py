"""Case management: creation, validated status workflow, assignment, notes, escalation (partner handoff), resolution.

Workflow (configurable via settings.case_transitions):
  DETECTED -> TRIAGED -> UNDER_REVIEW -> ASSIGNED -> ESCALATED -> RESOLVED
Documented shortcuts:  TRIAGED/UNDER_REVIEW/ASSIGNED -> RESOLVED  (dismiss / close with a required outcome + summary)
Backward moves:        UNDER_REVIEW -> TRIAGED, ASSIGNED -> UNDER_REVIEW, ESCALATED -> ASSIGNED (de-escalation)
Reopen:                RESOLVED -> UNDER_REVIEW (administrators / case:reopen only, comment required)
Special rules:         ASSIGNED requires an owner (use /assign); ESCALATED requires handoff details (use /escalate).
Nothing here closes a case or contacts a partner/platform automatically: every transition is a human action and
is recorded as an event + audit row. Model output alone never changes case status.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case as sa_case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailure
from app.core.permissions import has_permission
from app.models import (
    CaseAssignment, CaseEntity, CaseEscalation, CaseEvent, CaseNote, DigitalEntity, EvidenceRecord, InvestigationCase, User,
)
from app.models.enums import CaseEventType, CaseStatus, Severity, UserRole
from app.repositories.access import brand_scope, can_access_brand, get_brand_for_user, get_entity_for_user, is_admin
from app.schemas.case import CaseCreate, CaseStatusUpdate, EscalateRequest, ResolveRequest
from app.services import audit, case_notify
from app.services.analysis import latest_assessment
from app.services.scoring import severity_for

OPEN = [s for s in CaseStatus if s != CaseStatus.RESOLVED]
_TARGET_PERMISSION = {
    CaseStatus.TRIAGED: "case:triage", CaseStatus.UNDER_REVIEW: "case:triage", CaseStatus.ASSIGNED: "case:assign",
    CaseStatus.ESCALATED: "case:escalate", CaseStatus.RESOLVED: "case:resolve",
}
_SEV_RANK = {Severity.UNKNOWN: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}


# ---------- access ----------
def _require(actor: User, perm: str) -> None:
    if not has_permission(actor.role, perm):
        raise ForbiddenError(f"Your role does not permit this action ({perm})")


def _scope(actor: User, stmt):
    stmt = stmt.where(brand_scope(actor, InvestigationCase.brand_id))
    if actor.role == UserRole.PARTNER:  # partners only see cases that were handed off to them
        stmt = stmt.where(exists().where(CaseEscalation.case_id == InvestigationCase.id))
    return stmt


def get_case_for_user(db: Session, actor: User, case_id: uuid.UUID, *, lock: bool = False, detail: bool = False) -> InvestigationCase:
    # populate_existing: always return fresh column/relationship state (the identity map may hold a pre-commit copy)
    stmt = _scope(actor, select(InvestigationCase).where(InvestigationCase.id == case_id)).execution_options(populate_existing=True)
    if detail:
        stmt = stmt.options(
            selectinload(InvestigationCase.entities).selectinload(CaseEntity.entity), selectinload(InvestigationCase.notes).selectinload(CaseNote.author),
            selectinload(InvestigationCase.events).selectinload(CaseEvent.actor), selectinload(InvestigationCase.escalations),
            selectinload(InvestigationCase.assignments).selectinload(CaseAssignment.assignee),
        )
    if lock:
        stmt = stmt.with_for_update(of=InvestigationCase)
    case = db.scalar(stmt)
    if case is None:
        raise NotFoundError("Case not found")
    return case


def allowed_transitions(case: InvestigationCase, actor: User | None = None) -> list[CaseStatus]:
    out = []
    for t in get_settings().case_transitions.get(case.status.value, []):
        target = CaseStatus(t)
        if actor is not None:
            perm = "case:reopen" if case.status == CaseStatus.RESOLVED else _TARGET_PERMISSION.get(target)
            if perm and not has_permission(actor.role, perm):
                continue
        out.append(target)
    return out


def _event(db: Session, case: InvestigationCase, actor: User | None, etype: CaseEventType, *, frm=None, to=None, details=None) -> CaseEvent:
    ev = CaseEvent(case_id=case.id, event_type=etype, from_status=frm, to_status=to, actor_id=actor.id if actor else None, details=details or {})
    db.add(ev)
    return ev


def _touch(case: InvestigationCase) -> None:
    case.version += 1
    case.updated_at = datetime.now(UTC)


# ---------- creation ----------
def _next_case_number(db: Session) -> str:
    n = db.scalar(select(func.nextval("case_number_seq")))
    return f"NN-{datetime.now(UTC).year}-{n:06d}"


def _rollup(db: Session, entities: list[DigitalEntity]):
    """Case-level risk = highest member risk; confidence = mean member confidence (assessed members only)."""
    assessed = [e for e in entities if e.current_risk_score is not None]
    if not assessed:
        return None, None, Severity.UNKNOWN, None
    top = max(assessed, key=lambda e: e.current_risk_score)
    conf = sum(e.current_confidence or 0 for e in assessed) / len(assessed)
    la = latest_assessment(db, top.id)
    return round(top.current_risk_score, 4), round(conf, 4), severity_for(top.current_risk_score, get_settings()), la.id if la else None


def create_case(db: Session, actor: User, data: CaseCreate, *, idempotency_key: str | None = None, cluster_key: str | None = None):
    """Returns (case, created). Same Idempotency-Key from the same user returns the original case."""
    _require(actor, "case:create")
    if idempotency_key:
        prior = db.scalar(select(InvestigationCase).where(InvestigationCase.created_by_id == actor.id, InvestigationCase.idempotency_key == idempotency_key))
        if prior:
            return prior, False
    brand = get_brand_for_user(db, actor, data.brand_id)
    ids = list(dict.fromkeys(data.entity_ids))
    entities = [get_entity_for_user(db, actor, i) for i in ids]  # 404 if any entity is out of scope / unknown
    risk, conf, sev, aid = _rollup(db, entities)
    case = InvestigationCase(
        case_number=_next_case_number(db), brand_id=brand.id, title=data.title.strip(), summary=data.summary, status=CaseStatus.DETECTED,
        severity=sev, confidence=conf, risk_score=risk, risk_assessment_id=aid, cluster_key=cluster_key, created_by_id=actor.id,
        idempotency_key=idempotency_key, platforms=list(dict.fromkeys(data.platforms)),
    )
    db.add(case)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(InvestigationCase).where(InvestigationCase.created_by_id == actor.id, InvestigationCase.idempotency_key == idempotency_key))
        if prior:
            return prior, False
        raise
    top_id = max((e for e in entities if e.current_risk_score is not None), key=lambda e: e.current_risk_score, default=None)
    for e in entities:
        db.add(CaseEntity(case_id=case.id, entity_id=e.id, role="subject" if top_id and e.id == top_id.id else "related", added_by_id=actor.id))
    _event(db, case, actor, CaseEventType.CREATED, to=CaseStatus.DETECTED, details={"entity_ids": [str(i) for i in ids], "cluster_key": cluster_key})
    case_notify.on_case_created(db, case)  # single place for the case->notification mapping (see services/case_notify.py)
    audit.record(db, actor, "case.create", "case", case.id, details={"case_number": case.case_number, "entities": len(ids), "severity": sev.value}, organization_id=brand.organization_id)
    db.commit()
    return get_case_for_user(db, actor, case.id), True


def create_case_from_cluster(db: Session, actor: User, entity_ids: list[uuid.UUID], title: str | None, idempotency_key: str | None = None):
    from app.services import graph as graph_svc

    _require(actor, "case:create")
    g = graph_svc.build_graph(db, actor)
    import networkx as nx

    components: list[frozenset[str]] = []
    for i in dict.fromkeys(entity_ids):
        get_entity_for_user(db, actor, i)
        if str(i) not in g:
            raise NotFoundError("Entity not found in graph")
        comp = frozenset(nx.node_connected_component(g, str(i)))
        if comp not in components:
            components.append(comp)
    if len(components) > 1:
        raise ConflictError("The selected entities belong to different clusters; open one case per cluster or link them with a relationship first",
                            code="different_clusters", details={"clusters": [sorted(c) for c in components]})
    members: set[str] = set(components[0])
    if len(members) < 2:
        raise ConflictError("The selected entities have no relationships; a cluster needs at least two linked entities", code="not_a_cluster")
    summary = graph_svc.summarize_cluster(db, g, members)
    open_cases = [c for c in summary.existing_case_ids if db.scalar(select(InvestigationCase.status).where(InvestigationCase.id == uuid.UUID(c))) != CaseStatus.RESOLVED]
    if open_cases:
        raise ConflictError("Cluster is already covered by an open case", code="cluster_has_open_case", details={"case_ids": open_cases})
    ents = [db.get(DigitalEntity, uuid.UUID(m)) for m in members]
    top = max(ents, key=lambda e: e.current_risk_score or -1)
    sev = summary.max_severity
    text = f"{summary.headline}. " + ("Proposed by the platform: " if summary.propose_for_investigation else "Opened manually (below proposal thresholds: ") + "; ".join(summary.proposal_reasons) + (")" if not summary.propose_for_investigation else "")
    data = CaseCreate(brand_id=top.brand_id, title=title or f"Linked cluster: {top.display_name} (+{len(members) - 1})", summary=text, entity_ids=[e.id for e in ents])
    return create_case(db, actor, data, idempotency_key=idempotency_key, cluster_key=summary.cluster_id)


# ---------- status workflow ----------
def change_status(db: Session, actor: User, case_id: uuid.UUID, data: CaseStatusUpdate) -> InvestigationCase:
    case = get_case_for_user(db, actor, case_id, lock=True)
    if data.expected_status and case.status != data.expected_status:
        raise ConflictError(f"Case is currently '{case.status.value}', not '{data.expected_status.value}' (already changed?)", code="status_conflict")
    frm, to = case.status, data.status
    if frm == to:
        raise ConflictError(f"Case is already '{to.value}'", code="no_change")
    allowed = get_settings().case_transitions.get(frm.value, [])
    if to.value not in allowed:
        raise ConflictError(f"Transition {frm.value} -> {to.value} is not allowed", code="invalid_transition", details={"allowed": allowed})
    reopening = frm == CaseStatus.RESOLVED
    _require(actor, "case:reopen" if reopening else _TARGET_PERMISSION[to])
    if to == CaseStatus.ASSIGNED and case.assigned_to_id is None:
        raise ValidationFailure("A case needs an owner to be 'assigned'; use POST /cases/{id}/assign")
    if to == CaseStatus.ESCALATED:
        raise ValidationFailure("Escalation needs partner handoff details; use POST /cases/{id}/escalate")
    if to == CaseStatus.RESOLVED:
        if not data.resolution_outcome or not data.resolution_summary:
            raise ValidationFailure("resolution_outcome and resolution_summary are required to resolve a case")
        _apply_resolution(case, actor, data.resolution_outcome, data.resolution_summary)
    if reopening:
        if not data.comment:
            raise ValidationFailure("A comment explaining the reopen is required")
        case.resolved_at = case.resolved_by_id = case.resolution_outcome = case.resolution_summary = None
    case.status = to
    _touch(case)
    etype = CaseEventType.RESOLVED if to == CaseStatus.RESOLVED else CaseEventType.REOPENED if reopening else CaseEventType.STATUS_CHANGED
    _event(db, case, actor, etype, frm=frm, to=to, details={"comment": data.comment} if data.comment else {})
    if data.comment:
        db.add(CaseNote(case_id=case.id, author_id=actor.id, body=f"[status {frm.value} → {to.value}] {data.comment}"))
    case_notify.on_case_status(db, case, to)  # creator + assignee + admins (services/case_notify.py)
    audit.record(db, actor, "case.status_change", "case", case.id, details={"from": frm.value, "to": to.value}, organization_id=case.brand.organization_id)
    db.commit()
    return get_case_for_user(db, actor, case.id)


def _apply_resolution(case: InvestigationCase, actor: User, outcome, summary: str) -> None:
    case.resolution_outcome, case.resolution_summary = outcome, summary
    case.resolved_at, case.resolved_by_id = datetime.now(UTC), actor.id


def resolve(db: Session, actor: User, case_id: uuid.UUID, data: ResolveRequest) -> InvestigationCase:
    _require(actor, "case:resolve")
    return change_status(db, actor, case_id, CaseStatusUpdate(status=CaseStatus.RESOLVED, resolution_outcome=data.outcome, resolution_summary=data.summary))


# ---------- assignment ----------
def assign(db: Session, actor: User, case_id: uuid.UUID, assignee_id: uuid.UUID, note: str | None) -> InvestigationCase:
    _require(actor, "case:assign")
    case = get_case_for_user(db, actor, case_id, lock=True)
    if case.status in (CaseStatus.DETECTED, CaseStatus.TRIAGED):
        raise ConflictError("Move the case to 'under_review' before assigning it", code="invalid_state")
    if case.status == CaseStatus.RESOLVED:
        raise ConflictError("Resolved cases cannot be assigned; reopen the case first", code="invalid_state")
    assignee = db.get(User, assignee_id)
    if assignee is None or not assignee.is_active or assignee.role not in (UserRole.INVESTIGATOR, UserRole.ADMIN):
        raise ValidationFailure("Assignee must be an active investigator or administrator")
    if assignee.role != UserRole.ADMIN and not can_access_brand(db, assignee, case.brand):
        raise ValidationFailure("Assignee does not have access to this brand's organization")
    if case.assigned_to_id == assignee.id:
        return get_case_for_user(db, actor, case.id)  # idempotent repeat
    prev = case.assigned_to_id
    now = datetime.now(UTC)
    for open_row in db.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case.id, CaseAssignment.unassigned_at.is_(None))):
        open_row.unassigned_at = now
    db.flush()  # close the old row before inserting the new one (partial unique index: one open assignment)
    db.add(CaseAssignment(case_id=case.id, assignee_id=assignee.id, assigned_by_id=actor.id, assigned_at=now, note=note))
    case.assigned_to_id = assignee.id
    frm = case.status
    if case.status == CaseStatus.UNDER_REVIEW:
        case.status = CaseStatus.ASSIGNED
        _event(db, case, actor, CaseEventType.STATUS_CHANGED, frm=frm, to=CaseStatus.ASSIGNED, details={"reason": "owner assigned"})
    _event(db, case, actor, CaseEventType.REASSIGNED if prev else CaseEventType.ASSIGNED, frm=frm, to=case.status,
           details={"assignee_id": str(assignee.id), "assignee": assignee.email, "previous_assignee_id": str(prev) if prev else None, "note": note})
    _touch(case)
    case_notify.on_case_assigned(db, case, assignee.id)
    audit.record(db, actor, "case.reassign" if prev else "case.assign", "case", case.id, details={"assignee_id": str(assignee.id)}, organization_id=case.brand.organization_id)
    db.commit()
    return get_case_for_user(db, actor, case.id)


# ---------- notes / escalation / entities ----------
def add_note(db: Session, actor: User, case_id: uuid.UUID, body: str) -> CaseNote:
    _require(actor, "case:note")
    case = get_case_for_user(db, actor, case_id, lock=True)
    note = CaseNote(case_id=case.id, author_id=actor.id, body=body.strip())
    db.add(note)
    _event(db, case, actor, CaseEventType.NOTE_ADDED, details={"length": len(body)})
    _touch(case)
    audit.record(db, actor, "case.note", "case", case.id, organization_id=case.brand.organization_id)
    db.commit()
    db.refresh(note)
    return note


def escalate(db: Session, actor: User, case_id: uuid.UUID, data: EscalateRequest) -> InvestigationCase:
    _require(actor, "case:escalate")
    case = get_case_for_user(db, actor, case_id, lock=True)
    if case.status not in (CaseStatus.ASSIGNED, CaseStatus.ESCALATED):
        raise ConflictError("Only an assigned case can be escalated (it needs an owner first)", code="invalid_transition",
                            details={"current": case.status.value})
    frm = case.status
    esc = CaseEscalation(case_id=case.id, partner_type=data.partner_type, partner_contact=data.partner_contact, reason=data.reason,
                         requested_action=data.requested_action, created_by_id=actor.id)
    db.add(esc)
    case.status = CaseStatus.ESCALATED
    if frm != CaseStatus.ESCALATED:
        case.escalated_at = datetime.now(UTC)
    case.escalation_summary = f"{data.partner_type.value}: {data.reason}"[:2000]
    _touch(case)
    _event(db, case, actor, CaseEventType.ESCALATED, frm=frm, to=CaseStatus.ESCALATED,
           details={"partner_type": data.partner_type.value, "partner_contact": data.partner_contact, "note": "Handoff recorded only - no external takedown or notification was sent"})
    case_notify.on_case_escalated(db, case)  # administrators + current owner see the handoff
    audit.record(db, actor, "case.escalate", "case", case.id, details={"partner_type": data.partner_type.value}, organization_id=case.brand.organization_id)
    db.commit()
    return get_case_for_user(db, actor, case.id)


def add_entities(db: Session, actor: User, case_id: uuid.UUID, entity_ids: list[uuid.UUID], role: str = "related") -> InvestigationCase:
    _require(actor, "case:triage")
    case = get_case_for_user(db, actor, case_id, lock=True)
    if case.status == CaseStatus.RESOLVED:
        raise ConflictError("Cannot modify a resolved case", code="invalid_state")
    have = {ce.entity_id for ce in case.entities}
    for i in entity_ids:
        e = get_entity_for_user(db, actor, i)
        if e.id in have:
            continue
        db.add(CaseEntity(case_id=case.id, entity_id=e.id, role=role, added_by_id=actor.id))
        _event(db, case, actor, CaseEventType.ENTITY_ADDED, details={"entity_id": str(e.id)})
    db.flush()
    db.expire(case, ["entities"])
    ents = [ce.entity for ce in case.entities]
    case.risk_score, case.confidence, case.severity, case.risk_assessment_id = _rollup(db, ents)
    _touch(case)
    audit.record(db, actor, "case.entities_add", "case", case.id, details={"entity_ids": [str(i) for i in entity_ids]}, organization_id=case.brand.organization_id)
    db.commit()
    return get_case_for_user(db, actor, case.id)


# ---------- update / delete ----------
def update_case(db: Session, actor: User, case_id: uuid.UUID, body) -> InvestigationCase:
    """Edit title / summary / severity / platforms. Optional `version` guards against concurrent edits (409)."""
    _require(actor, "case:triage")
    case = get_case_for_user(db, actor, case_id, lock=True, detail=True)
    if body.version is not None and body.version != case.version:
        raise ConflictError(
            f"Case was modified by someone else (expected version {body.version}, current {case.version}); reload and retry",
            code="version_conflict", details={"current_version": case.version},
        )
    changes: dict = {}
    if body.title is not None and body.title.strip() != case.title:
        case.title = body.title.strip()
        changes["title"] = True
    if body.summary is not None and body.summary != case.summary:
        case.summary = body.summary
        changes["summary"] = True
    if body.severity is not None and body.severity != case.severity:
        changes["severity"] = [case.severity.value, body.severity.value]
        case.severity = body.severity
    if body.platforms is not None:
        new_platforms = list(dict.fromkeys(body.platforms))
        if new_platforms != list(case.platforms or []):
            changes["platforms"] = new_platforms
            case.platforms = new_platforms
    if not changes:
        return get_case_for_user(db, actor, case.id, detail=True)
    _touch(case)
    audit.record(db, actor, "case.update", "case", case.id, details=changes, organization_id=case.brand.organization_id)
    db.commit()
    return get_case_for_user(db, actor, case.id, detail=True)


def delete_case(db: Session, actor: User, case_id: uuid.UUID) -> None:
    """Administrators only. Cascades to notes/events/assignments/escalations/links; entities are kept."""
    if actor.role != UserRole.ADMIN:
        raise ForbiddenError("Only administrators may delete cases")
    case = get_case_for_user(db, actor, case_id, detail=True)
    details = {"case_number": case.case_number, "title": case.title, "status": case.status.value,
               "linked_entities": case.entity_count,
               "cascades": ["case_notes", "case_events", "case_assignments", "case_escalations", "case_entities", "case_evidence"],
               "kept": ["digital_entities", "evidence_records", "risk_assessments"]}
    audit.record(db, actor, "case.delete", "case", case.id, details=details, organization_id=case.brand.organization_id)
    db.delete(case)
    db.commit()


# ---------- queries ----------
SORTS = {"created_at": InvestigationCase.created_at, "updated_at": InvestigationCase.updated_at, "risk_score": InvestigationCase.risk_score,
         "confidence": InvestigationCase.confidence, "case_number": InvestigationCase.case_number}


def list_cases(db: Session, actor: User, *, page: int, page_size: int, brand_id=None, statuses=None, severities=None, assignee_id=None,
               unassigned: bool = False, entity_id=None, q: str | None = None, min_risk: float | None = None, open_only: bool = False,
               sort: str = "created_at", order: str = "desc"):
    stmt = _scope(actor, select(InvestigationCase))
    if brand_id:
        stmt = stmt.where(InvestigationCase.brand_id == brand_id)
    if statuses:
        stmt = stmt.where(InvestigationCase.status.in_(statuses))
    if open_only:
        stmt = stmt.where(InvestigationCase.status != CaseStatus.RESOLVED)
    if severities:
        stmt = stmt.where(InvestigationCase.severity.in_(severities))
    if assignee_id:
        stmt = stmt.where(InvestigationCase.assigned_to_id == assignee_id)
    if unassigned:
        stmt = stmt.where(InvestigationCase.assigned_to_id.is_(None))
    if entity_id:
        stmt = stmt.where(exists().where(CaseEntity.case_id == InvestigationCase.id, CaseEntity.entity_id == entity_id))
    if min_risk is not None:
        stmt = stmt.where(InvestigationCase.risk_score >= min_risk)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(InvestigationCase.title.ilike(like), InvestigationCase.case_number.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    if sort == "severity":
        col = sa_case({s.value: r for s, r in _SEV_RANK.items()}, value=InvestigationCase.severity, else_=0)
    else:
        col = SORTS[sort]
    col = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.scalars(stmt.options(selectinload(InvestigationCase.entities)).order_by(col, InvestigationCase.id).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return rows, total


def case_detail_dict(db: Session, actor: User, case: InvestigationCase) -> dict:
    from app.schemas.case import CaseDetail

    ents = []
    for ce in case.entities:
        e = ce.entity
        evid = db.scalars(select(EvidenceRecord).where(EvidenceRecord.entity_id == e.id).order_by(EvidenceRecord.created_at)).all()
        ents.append({"role": ce.role, "entity": e, "latest_assessment": latest_assessment(db, e.id), "evidence": hydrate(db, evid)})
    ra = None
    if case.risk_assessment_id:
        from app.models import RiskAssessment
        ra = db.scalar(select(RiskAssessment).where(RiskAssessment.id == case.risk_assessment_id).options(selectinload(RiskAssessment.signals)))
    case_evidence = []
    from app.models import CaseEvidenceLink
    from app.schemas.case import CaseEvidenceOut
    links = db.scalars(select(CaseEvidenceLink).where(CaseEvidenceLink.case_id == case.id).options(selectinload(CaseEvidenceLink.evidence))).all()
    for out, link in zip(hydrate(db, [l.evidence for l in links]), links):
        case_evidence.append(CaseEvidenceOut.model_validate({**out.model_dump(), "role": link.role}))
    return CaseDetail.model_validate({
        "id": case.id, "case_number": case.case_number, "brand_id": case.brand_id, "title": case.title, "status": case.status, "severity": case.severity,
        "confidence": case.confidence, "risk_score": case.risk_score, "assigned_to": case.assigned_to, "entity_count": case.entity_count,
        "created_at": case.created_at, "updated_at": case.updated_at, "resolved_at": case.resolved_at, "summary": case.summary, "cluster_key": case.cluster_key,
        "risk_assessment": ra, "escalated_at": case.escalated_at, "escalation_summary": case.escalation_summary, "resolution_outcome": case.resolution_outcome,
        "resolution_summary": case.resolution_summary, "resolved_by": case.resolved_by, "created_by": case.created_by, "entities": ents,
        "evidence": case_evidence, "notes": case.notes, "platforms": list(case.platforms or []),
        "events": case.events, "escalations": case.escalations, "assignments": case.assignments, "allowed_transitions": allowed_transitions(case, actor), "version": case.version,
    }, from_attributes=True)


def _ev(db: Session, x: EvidenceRecord):
    """EvidenceOut for one record, with case_ids + entity populated (delegates to services/evidence.hydrate)."""
    from app.services.evidence import to_out

    return to_out(db, x)


def hydrate(db: Session, rows):
    """Batch variant of `_ev` (2 queries for any number of rows)."""
    from app.services.evidence import hydrate as _h

    return _h(db, rows)


def cases_for_entity(db: Session, actor: User, entity_id: uuid.UUID):
    get_entity_for_user(db, actor, entity_id)
    return db.scalars(_scope(actor, select(InvestigationCase)).where(exists().where(CaseEntity.case_id == InvestigationCase.id, CaseEntity.entity_id == entity_id))
                      .options(selectinload(InvestigationCase.entities)).order_by(InvestigationCase.created_at.desc())).unique().all()
