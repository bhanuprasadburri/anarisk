"""App-store monitoring targets: validated package/URL intake, linked mobile_app entity, sample sync."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.models import Brand, DigitalEntity, MonitoringSyncRun, MonitoringTarget, User
from app.models.enums import EntityType, Provenance, Severity, SourceKind
from app.repositories.access import brand_scope, get_brand_for_user
from app.schemas.entity import EntitySubmit
from app.schemas.monitoring import MonitoringCreate, MonitoringPatch, MonitoringTargetOut
from app.services import analysis, audit, ingestion, scheduler
from app.utils.urls import parse_url

GOOGLE_PLAY_PACKAGE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
APP_STORE_NUMERIC = re.compile(r"^\d{8,15}$")
APP_STORE_SLUG = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,64}$")

SORTS = {
    "package_id": MonitoringTarget.package_id,
    "risk_score": DigitalEntity.current_risk_score,
    "last_seen_at": DigitalEntity.last_seen_at,
    "created_at": MonitoringTarget.created_at,
}


def validate_package(store: str, package_id: str) -> list[dict]:
    package_id = (package_id or "").strip()
    if store == "google_play":
        if not GOOGLE_PLAY_PACKAGE.fullmatch(package_id) or package_id.count(".") < 2:
            return [{"field": "package_id", "message":
                     "must be a Google Play package id with at least 3 dot-separated segments, e.g. com.example.app"}]
        return []
    if store == "app_store":
        if not (APP_STORE_NUMERIC.fullmatch(package_id) or APP_STORE_SLUG.fullmatch(package_id)):
            return [{"field": "package_id", "message":
                     "must be an App Store id: 8-15 digits (e.g. 1234567890) or an alphanumeric slug (3-65 chars)"}]
        return []
    if len(package_id) < 3:
        return [{"field": "package_id", "message": "must be at least 3 characters"}]
    return []


def validate_store_url(store: str, package_id: str, url: str) -> list[dict]:
    p = parse_url(url)
    if p is None or p.scheme != "https":
        return [{"field": "store_url", "message": "must be a valid https URL"}]
    if store == "other":
        return []
    if store == "google_play":
        path_ok = p.path.startswith("/store/apps/details")
        id_ok = f"id={package_id}" in (p.query or "")
        if p.host != "play.google.com" or not path_ok or not id_ok:
            return [{"field": "store_url", "message":
                     "must be https://play.google.com/store/apps/details?id=<the same package_id>"}]
        return []
    # app_store
    if p.host != "apps.apple.com" or not (p.path or "").rstrip("/").endswith(f"/id{package_id}"):
        return [{"field": "store_url", "message": f"must be https://apps.apple.com/.../app/id{package_id}"}]
    return []


def get_target(db: Session, actor: User, target_id: uuid.UUID) -> MonitoringTarget:
    t = db.scalar(
        select(MonitoringTarget).options(joinedload(MonitoringTarget.brand), joinedload(MonitoringTarget.entity))
        .where(MonitoringTarget.id == target_id)
    )
    if t is None or not brand_scope_applies(db, actor, t.brand_id):
        raise NotFoundError("Monitoring target not found")
    return t


def brand_scope_applies(db: Session, actor: User, brand_id: uuid.UUID) -> bool:
    from app.repositories.access import can_access_brand

    brand = db.get(Brand, brand_id)
    return brand is not None and can_access_brand(db, actor, brand)


def item_dict(t: MonitoringTarget) -> dict[str, Any]:
    e = t.entity
    attrs = (e.attributes or {}) if e else {}
    return {
        "id": t.id, "brand": {"id": t.brand.id, "name": t.brand.name}, "package_id": t.package_id,
        "store": t.store, "store_url": t.store_url, "monitoring_status": t.monitoring_status,
        "app_name": attrs.get("app_name"), "publisher_name": attrs.get("publisher_name"),
        "entity": None if e is None else {
            "id": e.id, "display_name": e.display_name, "risk_score": e.current_risk_score,
            "severity": e.current_severity.value, "confidence": e.current_confidence,
            "provenance": e.provenance.value, "last_seen_at": e.last_seen_at, "source_url": e.source_url,
        },
        "last_sync_at": t.last_sync_at, "created_at": t.created_at,
        "next_run_at": t.next_run_at, "retry_count": t.retry_count, "last_run_status": t.last_run_status,
    }


def _validate(store: str, package_id: str, store_url: str | None) -> None:
    problems = validate_package(store, package_id)
    if store_url:
        problems += validate_store_url(store, package_id.strip(), store_url)
    if problems:
        raise ValidationFailure("Invalid monitoring target", details=problems)


def create_target(db: Session, actor: User, body: MonitoringCreate) -> dict[str, Any]:
    brand = get_brand_for_user(db, actor, body.brand_id)
    package_id = body.package_id.strip()
    _validate(body.store, package_id, body.store_url)
    if db.scalar(select(MonitoringTarget.id).where(MonitoringTarget.brand_id == brand.id, MonitoringTarget.package_id == package_id)):
        raise ConflictError("This package is already monitored for this brand", code="duplicate_monitoring_target")
    # Create or link the mobile_app entity through the normal ingestion pipeline (SYNTHETIC sample provenance).
    entity, _created, official = ingestion.submit_entity(db, actor, EntitySubmit(
        brand_id=brand.id, entity_type=EntityType.MOBILE_APP, display_name=None,
        provenance=Provenance.SYNTHETIC, source_url=body.store_url, analyze=False,
        attributes={"app_name": package_id, "package_id": package_id, "store": body.store, "store_url": body.store_url},
    ))
    target = MonitoringTarget(brand_id=brand.id, package_id=package_id, store=body.store, store_url=body.store_url,
                              entity_id=entity.id, created_by_id=actor.id)
    db.add(target)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This package is already monitored for this brand", code="duplicate_monitoring_target")
    audit.record(db, actor, "monitoring_target.create", "monitoring_target", target.id,
                 details={"package_id": package_id, "store": body.store, "entity_id": str(entity.id),
                          "entity_provenance": entity.provenance.value},
                 organization_id=brand.organization_id)
    db.commit()
    scheduler.schedule_target(db, target.id)  # first scheduled check one interval from now
    return {"target": item_dict(get_target(db, actor, target.id)),
            "message": ("Monitoring target created and linked to a mobile_app entity ingested via the SYNTHETIC "
                        "sample pipeline (provenance=synthetic). No live app-store data was fetched.")}


def list_targets(db: Session, actor: User, *, page: int, page_size: int, q: str | None, brand_id: uuid.UUID | None,
                 store: str | None, risk_severity: Severity | None, monitoring_status: str | None, sort: str, order: str):
    stmt = (
        select(MonitoringTarget)
        .outerjoin(DigitalEntity, DigitalEntity.id == MonitoringTarget.entity_id)
        .where(brand_scope(actor, MonitoringTarget.brand_id))
    )
    if brand_id:
        stmt = stmt.where(MonitoringTarget.brand_id == brand_id)
    if store:
        stmt = stmt.where(MonitoringTarget.store == store)
    if monitoring_status:
        stmt = stmt.where(MonitoringTarget.monitoring_status == monitoring_status)
    if risk_severity:
        stmt = stmt.where(DigitalEntity.current_severity == risk_severity)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            MonitoringTarget.package_id.ilike(like),
            DigitalEntity.display_name.ilike(like),
            func.lower(DigitalEntity.attributes["app_name"].astext).ilike(like.lower()),
        ))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTS[sort]
    col = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.scalars(
        stmt.options(joinedload(MonitoringTarget.brand), joinedload(MonitoringTarget.entity))
        .order_by(col, MonitoringTarget.id).offset((page - 1) * page_size).limit(page_size)
    ).unique().all()
    return rows, total


def patch_target(db: Session, actor: User, target_id: uuid.UUID, body: MonitoringPatch) -> dict[str, Any]:
    t = get_target(db, actor, target_id)
    changes: dict = {}
    if body.monitoring_status is not None and body.monitoring_status != t.monitoring_status:
        t.monitoring_status = body.monitoring_status
        changes["monitoring_status"] = body.monitoring_status
    if body.store_url is not None and body.store_url != t.store_url:
        problems = validate_store_url(t.store, t.package_id, body.store_url)
        if problems:
            raise ValidationFailure("Invalid monitoring target", details=problems)
        t.store_url = body.store_url
        changes["store_url"] = "updated"
    if changes:
        audit.record(db, actor, "monitoring_target.update", "monitoring_target", t.id, details=changes)
        db.commit()
        if t.monitoring_status == "active":
            scheduler.schedule_target(db, t.id)  # explicit resume puts it back on the schedule
        elif t.monitoring_status == "paused":
            t.next_run_at = None  # paused targets are never picked up by the scheduler
            db.commit()
    return item_dict(get_target(db, actor, t.id))


def delete_target(db: Session, actor: User, target_id: uuid.UUID) -> None:
    t = get_target(db, actor, target_id)
    audit.record(db, actor, "monitoring_target.delete", "monitoring_target", t.id,
                 details={"package_id": t.package_id, "store": t.store, "brand_id": str(t.brand_id),
                          "kept": "the linked digital entity is kept; only the monitoring target is removed"})
    db.delete(t)
    db.commit()


def sync_target(db: Session, actor: User, target_id: uuid.UUID) -> dict[str, Any]:
    t = get_target(db, actor, target_id)
    started = datetime.now(UTC)
    run = MonitoringSyncRun(target_id=t.id, status="failed", triggered_by="manual", started_at=started)
    db.add(run)
    db.commit()
    try:
        return _sync_target_inner(db, actor, target_id, run)
    except Exception:
        run = db.get(MonitoringSyncRun, run.id)
        if run is not None:
            run.finished_at = datetime.now(UTC)
            run.error = "sync failed (see application logs)"
            db.commit()
        raise


def _sync_target_inner(db: Session, actor: User, target_id: uuid.UUID, run: MonitoringSyncRun) -> dict[str, Any]:
    t = get_target(db, actor, target_id)
    brand = get_brand_for_user(db, actor, t.brand_id)
    source = ingestion.ensure_source(db, "sample-listings", "Synthetic sample listings (demo)", SourceKind.SYNTHETIC,
                                     "Generates SYNTHETIC lookalike listings for demos - not real store data")
    canonical = f"{t.store}:{t.package_id.lower()}"
    existing = db.scalar(select(DigitalEntity).where(
        DigitalEntity.brand_id == brand.id, DigitalEntity.entity_type == EntityType.MOBILE_APP,
        DigitalEntity.canonical_id == canonical))
    app_name = ((existing.attributes or {}).get("app_name") if existing else None) or t.package_id
    norm = ingestion.normalize_submission(EntityType.MOBILE_APP, app_name, None, t.store_url, {
        "app_name": app_name, "package_id": t.package_id, "store": t.store, "store_url": t.store_url,
        "publisher_name": f"[SYNTHETIC SAMPLE] {brand.name} Digital Services Ltd",
        "description": (f"[SYNTHETIC SAMPLE] Sample listing data for {t.package_id}. "
                        "Generated by the demo connector - not fetched from the app store."),
        "permissions": ["INTERNET", "ACCESS_NETWORK_STATE"], "permissions_source": "manual",
        "linked_websites": [],
    })
    entity, created = ingestion.upsert_entity(db, brand, norm, Provenance.SYNTHETIC, source, actor, {
        "connector": "sample-listings", "monitoring_target": str(t.id),
        "note": "synthetic sample sync - not live app-store data",
    })
    t.entity_id, t.last_sync_at = entity.id, datetime.now(UTC)
    t.retry_count, t.last_run_status = 0, "success"
    run.status, run.finished_at, run.error = "success", datetime.now(UTC), None
    reanalyzed, official_reason = True, None
    try:
        analysis.analyze_entity(db, actor, entity, commit=False)
    except Exception as exc:  # official asset / detector guard: report honestly, never fail the sync
        reanalyzed, official_reason = False, getattr(exc, "message", str(exc))
    audit.record(db, actor, "monitoring_target.sync", "monitoring_target", t.id,
                 details={"package_id": t.package_id, "entity_id": str(entity.id), "created_entity": created,
                          "reanalyzed": reanalyzed, "provenance": "synthetic"},
                 organization_id=brand.organization_id)
    db.commit()
    scheduler.schedule_target(db, t.id)  # next scheduled check
    message = (f"Synced {t.package_id} via the SYNTHETIC sample connector (provenance=synthetic): attributes updated "
               "from SAMPLE data, not a live app-store fetch. "
               + ("Rule-based heuristic re-analysis completed." if reanalyzed
                  else f"Re-analysis skipped ({official_reason})."))
    return {"target": item_dict(get_target(db, actor, t.id)),
            "entity": _entity_dump(entity), "message": message}


def _entity_dump(entity: DigitalEntity) -> dict[str, Any]:
    from app.schemas.entity import EntityOut

    return EntityOut.model_validate(entity).model_dump(mode="json")
