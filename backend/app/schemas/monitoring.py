from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORM

Store = Literal["google_play", "app_store", "other"]
MonitoringStatus = Literal["active", "paused"]


class BrandBrief(BaseModel):
    id: uuid.UUID
    name: str


class EntityBriefMonitoring(BaseModel):
    """Linked mobile_app entity summary for the monitoring list."""

    id: uuid.UUID
    display_name: str
    risk_score: float | None = None
    severity: str = "unknown"
    confidence: float | None = None
    provenance: str = "synthetic"
    last_seen_at: datetime | None = None
    source_url: str | None = None


class MonitoringTargetOut(BaseModel):
    id: uuid.UUID
    brand: BrandBrief
    package_id: str
    store: Store
    store_url: str | None = None
    monitoring_status: MonitoringStatus = "active"
    app_name: str | None = None
    publisher_name: str | None = None
    entity: EntityBriefMonitoring | None = None
    last_sync_at: datetime | None = None
    created_at: datetime
    next_run_at: datetime | None = None
    retry_count: int = 0
    last_run_status: Literal["success", "failed"] | None = None


class MonitoringCreate(BaseModel):
    brand_id: uuid.UUID
    package_id: str = Field(min_length=3, max_length=255)
    store: Store = "google_play"
    store_url: str | None = Field(None, max_length=2048)


class MonitoringPatch(BaseModel):
    monitoring_status: MonitoringStatus | None = None
    store_url: str | None = Field(None, max_length=2048)


class MonitoringSyncResult(BaseModel):
    target: MonitoringTargetOut
    entity: dict | None = None
    message: str


class MonitoringCreateResult(BaseModel):
    target: MonitoringTargetOut
    message: str
