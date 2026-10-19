"""Best-effort in-app notifications.

`notify()` only ADDS rows to the caller's current transaction - it never raises and never commits, so a
failure here can never break the case/analysis flow it is called from. Recipients are explicit; helpers
below resolve "all administrators".
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models import Notification, User
from app.models.enums import Severity, UserRole
from app.services import audit

log = logging.getLogger(__name__)


def admins(db: Session) -> list[uuid.UUID]:
    from app.services.scheduler import SYSTEM_USER_EMAIL  # local import: avoids a module cycle

    return list(db.scalars(select(User.id).where(
        User.role == UserRole.ADMIN, User.is_active.is_(True), User.email != SYSTEM_USER_EMAIL)))


def notify(
    db: Session,
    user_ids,
    type: str,
    title: str,
    body: str | None = None,
    link_url: str | None = None,
    resource: tuple[str, uuid.UUID] | None = None,
    *,
    dedupe_hours: int | None = None,
) -> int:
    """Insert one notification per distinct recipient. Returns how many rows were added.

    When `dedupe_hours` is set, recipients that already received a notification of the same `type`
    for the same `resource` within the window are skipped.
    """
    created = 0
    seen: set[uuid.UUID] = set()
    try:
        with db.begin_nested():  # SAVEPOINT: a failure here never damages the caller's transaction
            for uid in dict.fromkeys(user_ids or []):
                if uid is None or uid in seen:
                    continue
                seen.add(uuid.UUID(str(uid)))
                if dedupe_hours and resource:
                    window_start = datetime.now(UTC) - timedelta(hours=dedupe_hours)
                    existing = db.scalar(
                        select(Notification.id).where(
                            Notification.user_id == uid, Notification.type == type,
                            Notification.resource_type == resource[0], Notification.resource_id == resource[1],
                            Notification.created_at >= window_start,
                        )
                    )
                    if existing:
                        continue
                db.add(Notification(
                    user_id=uid, type=type, title=title[:255], body=body, link_url=link_url[:512] if link_url else None,
                    resource_type=resource[0] if resource else None, resource_id=resource[1] if resource else None,
                ))
                created += 1
            db.flush()
    except Exception:  # notifications must NEVER break the main flow
        log.exception("notification insert failed (type=%s)", type)
        return 0
    return created


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
    ) or 0


def mark_read(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID] | None) -> tuple[int, int]:
    """Mark the given ids (or all) of the caller's notifications read. Returns (updated, unread_count)."""
    stmt = update(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    result = db.execute(stmt.values(is_read=True))
    db.commit()
    return result.rowcount or 0, unread_count(db, user_id)


def delete_notification(db: Session, actor: User, notification_id: uuid.UUID) -> None:
    """Delete one notification. Owners may delete their own; administrators may delete any.

    A notification belonging to someone else returns 404 (same convention as cross-tenant
    reads): the response never confirms that another user's notification exists.
    """
    from app.repositories.access import is_admin  # local import: keeps this module dependency-light

    row = db.get(Notification, notification_id)
    if row is None or (row.user_id != actor.id and not is_admin(actor)):
        raise NotFoundError("Notification not found")
    db.delete(row)
    audit.record(db, actor, "notification.delete", "notification", notification_id)
    db.commit()


def broadcast(db: Session, actor: User, title: str, message: str) -> tuple[int, int]:
    """Persist an administrator announcement for every active user (in-app rows only).

    Returns ``(recipients, created)``. Raises ``ServiceUnavailableError`` when recipients exist
    but nothing was stored — a broadcast is never reported as delivered unless the rows were
    actually written (notify() is all-or-nothing per call).
    """
    from app.services.scheduler import SYSTEM_USER_EMAIL  # local import: avoids a module cycle

    recipients = list(db.scalars(
        select(User.id).where(User.is_active.is_(True), User.email != SYSTEM_USER_EMAIL)
    ))
    created = notify(db, recipients, "broadcast", title, message)
    if recipients and created == 0:
        raise ServiceUnavailableError("The announcement could not be stored — nothing was delivered")
    audit.record(db, actor, "notification.broadcast", "announcement", None, details={"recipients": len(recipients)})
    db.commit()
    return len(recipients), created


def notify_high_risk(db: Session, entity, assessment) -> int:
    """Notify administrators about a high/critical assessment. Deduped per entity within 24 hours."""
    if assessment.severity not in (Severity.HIGH, Severity.CRITICAL):
        return 0
    risk = assessment.risk_score
    return notify(
        db, admins(db), "high_risk_detection",
        f"{assessment.severity.value.upper()} risk detection: {entity.display_name}",
        (f"Heuristic risk score {risk:.2f} ({assessment.severity.value}) for a {entity.entity_type.value} "
         f"({entity.provenance.value} data). Human review required - scores are unvalidated."),
        link_url=f"/entities/{entity.id}", resource=("entity", entity.id), dedupe_hours=24,
    )
