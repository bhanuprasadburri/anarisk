"""Persistent background monitoring scheduler.

The schedule lives in the database (``monitoring_targets.next_run_at``), not in an in-memory
timer, so it survives restarts and is safe with multiple worker processes: due targets are
claimed with ``FOR UPDATE SKIP LOCKED`` before being run.

Each execution is recorded as a :class:`MonitoringSyncRun` (status, error, timestamps) and
updates ``retry_count``/``last_run_status``/``next_run_at`` on the target. Failures back off
linearly (``MONITORING_BACKOFF_SECONDS * retry_count``) up to ``MONITORING_RETRY_MAX``; after
that the target stops being scheduled (``next_run_at = NULL``) and administrators are
notified so the failure cannot pass silently.

The worker itself is an asyncio task started with the FastAPI app (see ``app/main.py``). It
can be disabled with ``MONITORING_WORKER_ENABLED=false`` (recommended when running a
separate worker process).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models import MonitoringSyncRun, MonitoringTarget, User
from app.models.enums import UserRole

log = logging.getLogger(__name__)

SYSTEM_USER_EMAIL = "system@nimbus.local"
_task: asyncio.Task | None = None


def ensure_system_user(db: Session) -> User | None:
    """The service account that owns scheduled runs. Created on demand (password is unusable).

    Role: administrator. The scheduler performs cross-org work by design, so it needs the
    broadest scope. The account can never authenticate: its password hash is not a valid
    bcrypt value, it has no usable credentials, and it is excluded from notification lists.
    """
    user = db.scalar(select(User).where(User.email == SYSTEM_USER_EMAIL))
    if user is not None:
        return user if user.is_active else None
    user = User(
        email=SYSTEM_USER_EMAIL, full_name="Monitoring Scheduler (system)",
        hashed_password="!disabled!",  # not a valid bcrypt hash: this account can never log in
        role=UserRole.ADMIN, is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:  # concurrent creation: re-read
        db.rollback()
        user = db.scalar(select(User).where(User.email == SYSTEM_USER_EMAIL))
        return user if (user and user.is_active) else None
    log.info("Created the system scheduler account %s", SYSTEM_USER_EMAIL)
    return user


def claim_due(db: Session, *, now: datetime | None = None, limit: int = 10) -> list[uuid.UUID]:
    """Atomically claim due, active targets (safe across processes)."""
    now = now or datetime.now(UTC)
    rows = db.execute(
        select(MonitoringTarget.id)
        .where(MonitoringTarget.monitoring_status == "active", MonitoringTarget.next_run_at.is_not(None),
               MonitoringTarget.next_run_at <= now)
        .order_by(MonitoringTarget.next_run_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    ids = [r[0] for r in rows]
    if ids:
        # push each claimed target's next run into the future immediately so a crashed
        # worker cannot cause an immediate duplicate run; failures re-schedule with backoff
        db.execute(
            MonitoringTarget.__table__.update()
            .where(MonitoringTarget.id.in_(ids))
            .values(next_run_at=now + timedelta(seconds=get_settings().monitoring_interval_seconds))
        )
        db.commit()
    return ids


def run_target(db: Session, target_id: uuid.UUID, *, triggered_by: str = "scheduler") -> MonitoringSyncRun:
    """Execute one monitoring sync and record the honest outcome."""
    from app.services import monitoring, notifications  # local import: avoids a cycle

    s = get_settings()
    started = datetime.now(UTC)
    run = MonitoringSyncRun(target_id=target_id, status="failed", triggered_by=triggered_by, started_at=started)
    db.add(run)
    db.commit()
    target = db.scalar(
        select(MonitoringTarget).options(joinedload(MonitoringTarget.brand)).where(MonitoringTarget.id == target_id)
    )
    system_user = ensure_system_user(db)
    if target is None or system_user is None:
        run.status, run.error, run.finished_at = "failed", "target or system user unavailable", datetime.now(UTC)
        db.commit()
        return run
    try:
        monitoring.sync_target(db, system_user, target_id)  # raises on failure; commits on success
        run.status, run.error, run.finished_at = "success", None, datetime.now(UTC)
        target.retry_count, target.last_run_status = 0, "success"
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a scheduler must survive any connector failure
        db.rollback()
        target = db.get(MonitoringTarget, target_id)
        message = f"{type(exc).__name__}: {exc}"[:2000]
        run = db.get(MonitoringSyncRun, run.id) or run
        run.status, run.error, run.finished_at = "failed", message, datetime.now(UTC)
        if target is not None:
            target.retry_count = (target.retry_count or 0) + 1
            target.last_run_status = "failed"
            if target.retry_count <= s.monitoring_retry_max:
                target.next_run_at = datetime.now(UTC) + timedelta(
                    seconds=s.monitoring_backoff_seconds * target.retry_count)
            else:
                target.next_run_at = None  # stop retrying; surface loudly instead of silently looping
                notifications.notify(
                    db, notifications.admins(db), "monitoring_sync_failed",
                    f"Monitoring sync stopped for {target.package_id}",
                    f"After {target.retry_count} failed attempts the scheduled sync was stopped "
                    f"(last error: {message[:300]}). Resume it from Settings → Monitoring.",
                    link_url="/mobile-apps", resource=("monitoring_target", target.id), dedupe_hours=24,
                )
        log.warning("Scheduled sync failed for %s: %s", target_id, message)
        db.commit()
    return run


def run_due_once(db: Session | None = None, *, now: datetime | None = None, limit: int = 10) -> int:
    """Claim and run every due target once. Returns how many were processed. Used by tests."""
    own = db is None
    db = db or get_sessionmaker()()
    try:
        ids = claim_due(db, now=now, limit=limit)
        for tid in ids:
            run_target(db, tid)
        return len(ids)
    finally:
        if own:
            db.close()


def schedule_target(db: Session, target_id: uuid.UUID, *, first_run_in_seconds: int | None = None) -> None:
    """Put (or re-put) a target on the schedule. Called on create/resume."""
    s = get_settings()
    delta = first_run_in_seconds if first_run_in_seconds is not None else s.monitoring_interval_seconds
    t = db.get(MonitoringTarget, target_id)
    if t is not None and t.monitoring_status == "active":
        t.next_run_at = datetime.now(UTC) + timedelta(seconds=max(5, delta))
        if t.last_run_status == "failed" and t.retry_count > s.monitoring_retry_max:
            t.retry_count = 0  # explicit resume resets the retry budget
        db.commit()


async def _loop() -> None:
    s = get_settings()
    log.info("Monitoring scheduler started (interval=%ss, worker enabled)", s.monitoring_interval_seconds)
    while True:
        try:
            await asyncio.sleep(s.monitoring_interval_seconds)
            await asyncio.to_thread(run_due_once)
        except asyncio.CancelledError:
            log.info("Monitoring scheduler stopped")
            raise
        except Exception:  # noqa: BLE001 - the loop must never die
            log.exception("Monitoring scheduler iteration failed")


def start() -> None:
    global _task
    s = get_settings()
    if not s.monitoring_worker_enabled or s.environment == "test":
        log.info("Monitoring scheduler not started (MONITORING_WORKER_ENABLED=false or test environment)")
        return
    if _task is None or _task.done():
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("Monitoring scheduler not started: no running event loop (call start() from an async context)")
            return
        _task = loop.create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
