from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, tz_col, uuid_pk

INTEGRATION_STATUSES = ("not_configured", "configured", "error")
MONITORING_STATUSES = ("active", "paused")
APP_STORES = ("google_play", "app_store", "other")


class IntegrationConfig(TimestampMixin, Base):
    """Stored connector/integration settings.

    `config_encrypted` holds the FULL configuration (including secrets) encrypted with Fernet; only the
    key set / non-secret values are echoed in `config_keys` - secret VALUES are never echoed outside the
    encrypted blob and are never returned by the API.
    """

    __tablename__ = "integration_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_key", name="uq_integration_configs_org_provider"),
        CheckConstraint("status IN ('not_configured', 'configured', 'error')", name="status_values"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="not_configured", nullable=False)
    config_encrypted: Mapped[str | None] = mapped_column(Text)
    config_keys: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)  # non-secret echo only
    last_sync_at: Mapped[datetime | None] = tz_col()
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    connected_by: Mapped["User | None"] = relationship(foreign_keys=[connected_by_id])  # noqa: F821


class MonitoringTarget(TimestampMixin, Base):
    """A package (app-store listing) being monitored for a brand. One row per brand + package."""

    __tablename__ = "monitoring_targets"
    __table_args__ = (
        UniqueConstraint("brand_id", "package_id", name="uq_monitoring_targets_brand_package"),
        CheckConstraint("store IN ('google_play', 'app_store', 'other')", name="store_values"),
        CheckConstraint("monitoring_status IN ('active', 'paused')", name="monitoring_status_values"),
        Index("ix_monitoring_targets_due", "monitoring_status", "next_run_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="mobile_app", nullable=False)
    package_id: Mapped[str] = mapped_column(String(255), nullable=False)
    store: Mapped[str] = mapped_column(String(32), default="google_play", nullable=False)
    store_url: Mapped[str | None] = mapped_column(Text)
    monitoring_status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("digital_entities.id", ondelete="SET NULL"), index=True
    )
    last_sync_at: Mapped[datetime | None] = tz_col()
    # ---- background scheduler (persistent: survives restarts; not an in-memory timer) ----
    next_run_at: Mapped[datetime | None] = tz_col()
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_run_status: Mapped[str | None] = mapped_column(String(16))  # success | failed
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    brand: Mapped["Brand"] = relationship()  # noqa: F821
    entity: Mapped["DigitalEntity | None"] = relationship()  # noqa: F821


class MonitoringSyncRun(Base):
    """One row per monitoring sync execution (manual or scheduled). Tracks honest outcomes and retries."""

    __tablename__ = "monitoring_sync_runs"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failed')", name="status_values"),
        CheckConstraint("triggered_by IN ('manual', 'scheduler')", name="triggered_by_values"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = tz_col(nullable=False)
    finished_at: Mapped[datetime | None] = tz_col()
