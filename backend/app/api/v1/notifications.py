from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import uuid

from app.api.deps import Pagination, get_current_user, require_permission
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import Notification, User
from app.schemas.notification import (
    BroadcastRequest, BroadcastResponse, MarkReadRequest, MarkReadResponse, NotificationPage, NotificationOut,
)
from app.services import notifications as svc

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationPage, summary="Your notifications (newest first) plus a top-level unread_count")
def list_(p: Pagination = Depends(), unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Notification.created_at.desc(), Notification.id)
        .offset((p.page - 1) * p.page_size).limit(p.page_size)
    ).all()
    pages = max(1, -(-total // p.page_size)) if p.page_size else 1
    return NotificationPage(
        items=[NotificationOut.model_validate(r) for r in rows], total=total,
        unread_count=svc.unread_count(db, user.id), page=p.page, page_size=p.page_size, pages=pages,
    )


@router.post("/read", response_model=MarkReadResponse, summary="Mark notifications read (omit ids to mark ALL read)")
def mark_read(body: MarkReadRequest | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = body.ids if body else None
    updated, unread = svc.mark_read(db, user.id, ids)
    return MarkReadResponse(updated=updated, unread_count=unread)


@router.post("/broadcast", response_model=BroadcastResponse,
             dependencies=[Depends(rate_limit("broadcast", "login_rate_limit_per_minute"))],
             summary="Administrator announcement: persists one in-app notification for every active user "
                     "(delivery counts are reported honestly — rows are only counted once stored)")
def broadcast(body: BroadcastRequest, user: User = Depends(require_permission("org:manage")), db: Session = Depends(get_db)):
    recipients, created = svc.broadcast(db, user, body.title, body.message)
    return BroadcastResponse(recipients=recipients, created=created)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete one of your notifications (administrators may delete any user's)")
def delete_(notification_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.delete_notification(db, user, notification_id)
