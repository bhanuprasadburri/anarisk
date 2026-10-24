import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, require_permission
from app.db.session import get_db
from app.models import User
from app.models.enums import CaseStatus, Severity
from app.schemas.case import (
    AssignmentOut, CaseAssign, CaseCreate, CaseDetail, CaseEntityLink, CasePatch, CaseStatusUpdate, CaseSummary, EscalateRequest, NoteCreate, NoteOut,
    ResolveRequest, TakedownReportOut,
)
from app.schemas.common import Page
from app.schemas.graph import GraphResponse
from app.services import cases as svc
from app.services import graph as graph_svc

router = APIRouter(prefix="/cases", tags=["Cases & Response Workflow"])


def _detail(db, user, case):
    return svc.case_detail_dict(db, user, svc.get_case_for_user(db, user, case.id, detail=True))


@router.post("", response_model=CaseDetail, status_code=201, summary="Create a case (initial status DETECTED). Send Idempotency-Key to make retries safe.")
def create(body: CaseCreate, response: Response, idempotency_key: str | None = Header(None, max_length=100), user: User = Depends(require_permission("case:create")), db: Session = Depends(get_db)):
    case, created = svc.create_case(db, user, body, idempotency_key=idempotency_key)
    if not created:
        response.status_code = 200
    return _detail(db, user, case)


@router.get("", response_model=Page[CaseSummary], summary="List cases: pagination, filtering, sorting")
def list_(p: Pagination = Depends(), brand_id: uuid.UUID | None = None, status: list[CaseStatus] | None = Query(None), severity: list[Severity] | None = Query(None),
          assignee_id: uuid.UUID | None = None, unassigned: bool = False, mine: bool = False, entity_id: uuid.UUID | None = None, open_only: bool = False,
          min_risk: float | None = Query(None, ge=0, le=1), q: str | None = Query(None, max_length=100),
          sort: str = Query("created_at", pattern="^(created_at|updated_at|risk_score|confidence|case_number|severity)$"), order: str = Query("desc", pattern="^(asc|desc)$"),
          user: User = Depends(require_permission("case:read")), db: Session = Depends(get_db)):
    rows, total = svc.list_cases(db, user, page=p.page, page_size=p.page_size, brand_id=brand_id, statuses=status, severities=severity,
                                 assignee_id=user.id if mine else assignee_id, unassigned=unassigned, entity_id=entity_id, q=q, min_risk=min_risk,
                                 open_only=open_only, sort=sort, order=order)
    return Page.build([CaseSummary.model_validate(r) for r in rows], total, p.page, p.page_size)


@router.get("/workflow", response_model=dict, summary="Configured workflow transitions")
def workflow(_: User = Depends(get_current_user)):
    from app.core.config import get_settings
    return {"transitions": get_settings().case_transitions}


@router.get("/{case_id}", response_model=CaseDetail, summary="Case detail: evidence, signals, linked entities, notes, status history, escalations")
def get(case_id: uuid.UUID, user: User = Depends(require_permission("case:read")), db: Session = Depends(get_db)):
    return svc.case_detail_dict(db, user, svc.get_case_for_user(db, user, case_id, detail=True))


@router.get("/{case_id}/takedown-report", response_model=TakedownReportOut,
            summary="Preview an evidence-backed takedown report draft for a confirmed case; does not submit it")
def takedown_report(case_id: uuid.UUID, user: User = Depends(require_permission("case:resolve")), db: Session = Depends(get_db)):
    return svc.takedown_report_draft(db, user, case_id)


@router.get("/{case_id}/graph", response_model=GraphResponse,
            summary="Case sub-graph: the case's linked entities + relationships among them (composed server-side, brand-scoped)")
def graph(case_id: uuid.UUID, user: User = Depends(require_permission("case:read")), db: Session = Depends(get_db)):
    case = svc.get_case_for_user(db, user, case_id, detail=True)
    return graph_svc.case_graph(db, user, case)


@router.patch("/{case_id}", response_model=CaseDetail,
              summary="Edit title / summary / severity / platforms (case:triage). Send `version` for optimistic concurrency -> 409 on conflict")
def patch(case_id: uuid.UUID, body: CasePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, user, svc.update_case(db, user, case_id, body))


@router.delete("/{case_id}", status_code=204,
               summary="Delete a case (administrators only). Notes/events/links cascade; entities and evidence are kept")
def delete(case_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.delete_case(db, user, case_id)


@router.post("/{case_id}/status", response_model=CaseDetail, summary="Validated status transition (use expected_status to guard against duplicate/racing requests)")
def status(case_id: uuid.UUID, body: CaseStatusUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, user, svc.change_status(db, user, case_id, body))


@router.post("/{case_id}/assign", response_model=CaseDetail, summary="Assign or reassign the owner (UNDER_REVIEW -> ASSIGNED automatically)")
def assign(case_id: uuid.UUID, body: CaseAssign, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, user, svc.assign(db, user, case_id, body.assignee_id, body.note))


@router.post("/{case_id}/notes", response_model=NoteOut, status_code=201)
def note(case_id: uuid.UUID, body: NoteCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.add_note(db, user, case_id, body.body)


@router.post("/{case_id}/escalate", response_model=CaseDetail, summary="Record an escalation / partner handoff (legal, marketing, platform). Does NOT contact anyone or request a takedown.")
def escalate(case_id: uuid.UUID, body: EscalateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, user, svc.escalate(db, user, case_id, body))


@router.post("/{case_id}/resolve", response_model=CaseDetail, summary="Resolve with an outcome and summary")
def resolve(case_id: uuid.UUID, body: ResolveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, user, svc.resolve(db, user, case_id, body))


@router.post("/{case_id}/entities", response_model=CaseDetail, summary="Link more entities to an open case")
def add_entities(case_id: uuid.UUID, body: list[CaseEntityLink], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    role = body[0].role if body else "related"
    return _detail(db, user, svc.add_entities(db, user, case_id, [b.entity_id for b in body], role))


@router.get("/{case_id}/assignments", response_model=list[AssignmentOut])
def assignments(case_id: uuid.UUID, user: User = Depends(require_permission("case:read")), db: Session = Depends(get_db)):
    return svc.get_case_for_user(db, user, case_id, detail=True).assignments
