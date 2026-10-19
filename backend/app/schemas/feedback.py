from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import FeedbackCategory, FeedbackStatus
from app.schemas.common import ORM


class FeedbackCreate(BaseModel):
    category: FeedbackCategory
    message: str = Field(min_length=1, max_length=4000)
    page_ref: str | None = Field(None, max_length=500, description="Page or feature this feedback refers to (optional)")
    brand_id: uuid.UUID | None = Field(None, description="Must be a brand inside the submitter's scope (optional)")
    related_case_id: uuid.UUID | None = Field(None, description="Must be a case the submitter can read (optional)")


class FeedbackOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    brand_id: uuid.UUID | None
    category: FeedbackCategory
    message: str
    page_ref: str | None
    related_case_id: uuid.UUID | None
    status: FeedbackStatus
    user_email: str | None = None  # populated for triage (admin view) / echo on submit
    created_at: datetime
    updated_at: datetime


class FeedbackStatusUpdate(BaseModel):
    status: FeedbackStatus
