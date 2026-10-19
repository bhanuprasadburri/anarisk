"""On-demand investigation tools: email/phishing, job offer, social profile, URL scanner, image review."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, require_permission
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.tools import (
    EmailAnalysisRequest, JobAnalysisRequest, SocialAnalysisRequest, ToolAnalysisListOut, ToolAnalysisOut, UrlAnalysisRequest,
)
from app.services import tools as tools_svc

router = APIRouter(prefix="/tools", tags=["Investigation Tools"])

_analyze_deps = [Depends(require_permission("entity:submit")), Depends(rate_limit("analyze", "analyze_rate_limit_per_minute"))]


@router.post("/email/analyze", response_model=ToolAnalysisOut, status_code=201, dependencies=_analyze_deps,
             summary="Analyze a pasted email or uploaded .eml for phishing signals (sender, SPF/DMARC, links, language, attachments metadata)")
def analyze_email(body: EmailAnalysisRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return tools_svc.run_email_analysis(db, user, body.model_dump(exclude_none=True))


@router.post("/job/analyze", response_model=ToolAnalysisOut, status_code=201, dependencies=_analyze_deps,
             summary="Assess a job offer / recruiter (employer identity, email-domain mismatch, fee requests, application link)")
def analyze_job(body: JobAnalysisRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return tools_svc.run_job_analysis(db, user, body.model_dump(exclude_none=True))


@router.post("/social/analyze", response_model=ToolAnalysisOut, status_code=201, dependencies=_analyze_deps,
             summary="Assess a social profile against official brand references (handles, names, linked domains). "
                     "Provider-verified identity is only claimed when a real platform connector is configured.")
def analyze_social(body: SocialAnalysisRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return tools_svc.run_social_analysis(db, user, body.model_dump(exclude_none=True))


@router.post("/url/analyze", response_model=ToolAnalysisOut, status_code=201, dependencies=_analyze_deps,
             summary="Scan a URL: canonicalisation, DNS (public-only), TLS certificate, SPF/DMARC, lookalike domain, "
                     "offline heuristics; live fetch only when URL_FETCH_ENABLED=true")
def analyze_url(body: UrlAnalysisRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return tools_svc.run_url_analysis(db, user, body.model_dump())


@router.post("/image/analyze", response_model=ToolAnalysisOut, status_code=201, dependencies=_analyze_deps,
             summary="Analyze an uploaded image: content-based validation, official-logo perceptual similarity, "
                     "embedded metadata and (when configured) AI review of the content — context: email | job_offer | social_profile")
async def analyze_image(
    file: UploadFile = File(..., description="Image file (validated by content, not extension)"),
    context: Literal["email", "job_offer", "social_profile"] = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.config import get_settings

    # Never buffer more than the configured limit + 1 marker byte; inspect_image then
    # reports an honest 413 for anything over the limit (and 422 for non-images).
    data = await file.read(get_settings().max_upload_bytes + 1)
    return tools_svc.run_image_analysis(
        db, user, data=data, filename=(file.filename or "image")[:255], context=context,
    )


@router.get("/analyses", response_model=ToolAnalysisListOut, summary="List your organization's past tool runs (newest first)")
def list_analyses(
    tool: str | None = Query(None, pattern="^(email|job_offer|social_profile|url|image)$"),
    pagination: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("entity:read")),
):
    result = tools_svc.list_analyses(db, user, tool=tool, page=pagination.page, page_size=pagination.page_size)
    return ToolAnalysisListOut(
        items=[ToolAnalysisOut.model_validate(r, from_attributes=True) for r in result["items"]],
        total=result["total"], page=result["page"], page_size=result["page_size"],
    )


@router.get("/analyses/{analysis_id}", response_model=ToolAnalysisOut, summary="Fetch one stored analysis")
def get_analysis(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("entity:read"))):
    return tools_svc.get_analysis(db, user, analysis_id)
