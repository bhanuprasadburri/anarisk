"""Feedback submissions (any authenticated user) + the authorized admin view.

Isolation rules:
- brand_id is validated against the submitter's brand scope (out-of-scope brand -> 404).
- related_case_id is validated with the same case access check the case API uses.
- GET / PATCH are administrator-only (org:manage); the list is global for triage.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import Pagination, get_current_user, require_permission
from app.core.errors import NotFoundError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import Feedback, User
from app.models.enums import FeedbackCategory, FeedbackStatus
from app.repositories.access import get_brand_for_user
from app.schemas.common import Page
from app.schemas.feedback import FeedbackCreate, FeedbackOut, FeedbackStatusUpdate
from app.services import audit
from app.services.cases import get_case_for_user

router = APIRouter(prefix="/feedback", tags=["Feedback"])


def _out(row: Feedback) -> FeedbackOut:
    out = FeedbackOut.model_validate(row)
    out.user_email = row.user.email if row.user is not None else None
    return out


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("feedback", "login_rate_limit_per_minute"))],
             summary="Submit feedback (bug/feature/content/other) for your brand scope")
def create(body: FeedbackCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    brand_id = None
    if body.brand_id is not None:
        # get_brand_for_user raises 404 for brands outside the submitter's scope
        brand_id = get_brand_for_user(db, user, body.brand_id).id
    related_case_id = None
    if body.related_case_id is not None:
        related_case_id = get_case_for_user(db, user, body.related_case_id).id
    row = Feedback(
        user_id=user.id,
        organization_id=user.organization_id,
        brand_id=brand_id,
        category=body.category,
        message=body.message.strip(),
        page_ref=body.page_ref,
        related_case_id=related_case_id,
        status=FeedbackStatus.OPEN,
    )
    db.add(row)
    audit.record(db, user, "feedback.create", "feedback", row.id, details={"category": body.category.value})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("", response_model=Page[FeedbackOut],
            summary="All feedback submissions (administrators only; filter by status/category)")
def list_(p: Pagination = Depends(), status_filter: FeedbackStatus | None = Query(None, alias="status"),
          category: FeedbackCategory | None = None, user: User = Depends(require_permission("org:manage")),
          db: Session = Depends(get_db)):
    stmt = select(Feedback)
    if status_filter is not None:
        stmt = stmt.where(Feedback.status == status_filter)
    if category is not None:
        stmt = stmt.where(Feedback.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Feedback.created_at.desc(), Feedback.id)
        .offset((p.page - 1) * p.page_size)
        .limit(p.page_size)
        .options(joinedload(Feedback.user))
    ).unique().all()
    return Page[FeedbackOut].build([_out(r) for r in rows], total, p.page, p.page_size)


@router.patch("/{feedback_id}", response_model=FeedbackOut,
              summary="Set a submission's status (administrators only)")
def update(feedback_id: uuid.UUID, body: FeedbackStatusUpdate, user: User = Depends(require_permission("org:manage")),
           db: Session = Depends(get_db)):
    row = db.get(Feedback, feedback_id)
    if row is None:
        raise NotFoundError("Feedback not found")
    if row.status != body.status:
        row.status = body.status
        audit.record(db, user, "feedback.status", "feedback", feedback_id, details={"status": body.status.value})
        db.commit()
        db.refresh(row)
    return _out(row)
