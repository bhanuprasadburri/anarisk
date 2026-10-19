import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import User
from app.models.enums import Provenance
from app.services import dashboard as svc

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", summary="Totals, risk/type distribution, recent detections, latest activity (database-backed)")
def stats(brand_id: uuid.UUID | None = None, provenance: Provenance | None = None,
          user: User = Depends(require_permission("dashboard:read")), db: Session = Depends(get_db)):
    return svc.stats(db, user, brand_id, provenance)


@router.get("/mobile-apps", summary="Mobile app monitoring summary")
def mobile_apps(brand_id: uuid.UUID | None = None, limit: int = Query(25, ge=1, le=100), user: User = Depends(require_permission("dashboard:read")), db: Session = Depends(get_db)):
    return svc.mobile_apps(db, user, brand_id, limit)
