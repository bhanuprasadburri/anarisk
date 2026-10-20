from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORM


class EmailAnalysisRequest(BaseModel):
    """Either `raw_email` (.eml text) OR the individual fields, plus optional claimed identity."""

    raw_email: str | None = Field(None, max_length=1_000_000)
    from_address: str | None = Field(None, max_length=320)
    from_name: str | None = Field(None, max_length=200)
    reply_to: str | None = Field(None, max_length=320)
    return_path: str | None = Field(None, max_length=320)
    subject: str | None = Field(None, max_length=500)
    body: str | None = Field(None, max_length=100_000)
    attachments: list[dict[str, Any]] | None = None
    claimed_brand: str | None = Field(None, max_length=200)
    claimed_domain: str | None = Field(None, max_length=255)

    @field_validator("attachments")
    @classmethod
    def _limit_attachments(cls, v):
        if v is None:
            return v
        if len(v) > 25:
            raise ValueError("at most 25 attachments may be described")
        return v


class JobAnalysisRequest(BaseModel):
    job_description: str | None = Field(None, max_length=100_000)
    offer_text: str | None = Field(None, max_length=100_000)
    employer_name: str | None = Field(None, max_length=200)
    employer_website: str | None = Field(None, max_length=2048)
    recruiter_name: str | None = Field(None, max_length=200)
    recruiter_profile_url: str | None = Field(None, max_length=2048)
    recruiter_email: str | None = Field(None, max_length=320)
    application_url: str | None = Field(None, max_length=2048)

    @field_validator("recruiter_email")
    @classmethod
    def _email_shape(cls, v):
        if v and "@" not in v:
            raise ValueError("recruiter_email must contain an @")
        return v


class SocialAnalysisRequest(BaseModel):
    platform: str | None = Field(None, max_length=40)
    profile_url: str | None = Field(None, max_length=2048)
    handle: str | None = Field(None, max_length=100)
    display_name: str | None = Field(None, max_length=200)
    bio: str | None = Field(None, max_length=5000)
    claimed_brand: str | None = Field(None, max_length=200)


class UrlAnalysisRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    share_with_phishtank: bool = False


class FindingOut(BaseModel):
    check: str
    title: str
    status: Literal["verified", "suspicious", "inconclusive", "unable_to_verify", "info"]
    severity: Literal["none", "low", "medium", "high", "critical", "unknown"]
    summary: str = ""
    evidence: list[str] = []
    source: str = ""
    limitation: str | None = None
    weight: float = 1.0


class ToolAnalysisOut(ORM):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    tool: str
    subject: str
    input_summary: dict[str, Any] | None = None
    findings: list[FindingOut] = []
    risk_score: float | None = None
    severity: str
    confidence: float | None = None
    methodology_version: str
    created_at: datetime


class ToolAnalysisListOut(BaseModel):
    items: list[ToolAnalysisOut]
    total: int
    page: int
    page_size: int
