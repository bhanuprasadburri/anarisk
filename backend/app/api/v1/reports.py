"""Report endpoints: aggregate overview + CSV exports.

Permission model (documented, uses only existing permissions):
  * GET /reports/overview            -> dashboard:read  (same model as /dashboard/*)
  * GET /reports/export/csv?report=  -> threats: entity:read | cases: case:read
                                        entities: entity:read | apps: entity:read
                                        evidence: evidence:read
  An unknown `report` value is rejected by the service with 422 before any data
  is read, so it never bypasses the permission mapping above.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.errors import ForbiddenError
from app.core.permissions import has_permission
from app.db.session import get_db
from app.models import User
from app.models.enums import Provenance
from app.services import reports as svc

router = APIRouter(prefix="/reports", tags=["Reports"])

REPORT_PERMISSIONS: dict[str, str] = {
    "threats": "entity:read",
    "cases": "case:read",
    "entities": "entity:read",
    "apps": "entity:read",
    "evidence": "evidence:read",
}


@router.get("/overview", summary="Aggregate risk/case/evidence overview for a date range (empty DB returns zeros)")
def overview(
    from_: str | None = Query(None, alias="from", description="ISO date (yyyy-mm-dd); default 30 days ago"),
    to: str | None = Query(None, alias="to", description="ISO date (yyyy-mm-dd); default today"),
    brand_id: uuid.UUID | None = None,
    provenance: Provenance | None = None,
    user: User = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    return svc.overview(db, user, from_, to, brand_id, provenance)


@router.get("/export/csv", summary="CSV export: report=threats|cases|entities|apps|evidence (attachment download)")
def export_csv(
    report: str = Query(..., description="threats | cases | entities | apps | evidence"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    brand_id: uuid.UUID | None = None,
    provenance: Provenance | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    perm = REPORT_PERMISSIONS.get(report)
    if perm and not has_permission(user.role, perm):
        # unknown report values fall through to the service, which rejects them with 422
        # BEFORE reading any data - so this mapping cannot be bypassed.
        raise ForbiddenError(f"Your role does not permit this action ({perm})")
    filename, content = svc.export_csv(db, user, report, from_, to, brand_id, provenance)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
