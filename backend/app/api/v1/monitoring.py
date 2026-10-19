import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, require_permission
from app.db.session import get_db
from app.models import User
from app.models.enums import Severity
from app.schemas.common import Page
from app.schemas.monitoring import MonitoringCreate, MonitoringCreateResult, MonitoringPatch, MonitoringSyncResult, MonitoringTargetOut
from app.services import monitoring as svc

router = APIRouter(prefix="/monitoring", tags=["App Monitoring"])


@router.get("/apps", response_model=Page[MonitoringTargetOut],
            summary="Monitored apps: package, store, status + linked entity risk. Filters: q, store, brand_id, risk_severity, monitoring_status, sort, order")
def list_apps(p: Pagination = Depends(), q: str | None = Query(None, max_length=100), brand_id: uuid.UUID | None = None,
              store: str | None = Query(None, pattern="^(google_play|app_store|other)$"),
              risk_severity: Severity | None = None,
              monitoring_status: str | None = Query(None, pattern="^(active|paused)$"),
              sort: str = Query("created_at", pattern="^(package_id|risk_score|last_seen_at|created_at)$"),
              order: str = Query("desc", pattern="^(asc|desc)$"),
              user: User = Depends(require_permission("entity:read")), db: Session = Depends(get_db)):
    rows, total = svc.list_targets(db, user, page=p.page, page_size=p.page_size, q=q, brand_id=brand_id, store=store,
                                   risk_severity=risk_severity, monitoring_status=monitoring_status, sort=sort, order=order)
    return Page.build([MonitoringTargetOut.model_validate(svc.item_dict(r)) for r in rows], total, p.page, p.page_size)


@router.post("/apps", response_model=MonitoringCreateResult, status_code=201,
             summary="Start monitoring a package. Validates the package id + store URL; 409 duplicate_monitoring_target on repeats")
def create_app(body: MonitoringCreate, user: User = Depends(require_permission("entity:submit")), db: Session = Depends(get_db)):
    return svc.create_target(db, user, body)


@router.patch("/apps/{target_id}", response_model=MonitoringTargetOut, summary="Pause/resume monitoring or correct the store URL")
def patch_app(target_id: uuid.UUID, body: MonitoringPatch, user: User = Depends(require_permission("entity:submit")),
              db: Session = Depends(get_db)):
    return svc.patch_target(db, user, target_id, body)


@router.delete("/apps/{target_id}", status_code=204, summary="Stop monitoring this package (the linked entity is kept)")
def delete_app(target_id: uuid.UUID, user: User = Depends(require_permission("entity:submit")), db: Session = Depends(get_db)):
    svc.delete_target(db, user, target_id)


@router.post("/apps/{target_id}/sync", response_model=MonitoringSyncResult,
             summary="Run the sample connector for this app (SYNTHETIC data - stated honestly) and re-analyze the linked entity")
def sync_app(target_id: uuid.UUID, user: User = Depends(require_permission("connector:run")), db: Session = Depends(get_db)):
    return svc.sync_target(db, user, target_id)
