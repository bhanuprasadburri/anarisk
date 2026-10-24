from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, tz_col, uuid_pk, utcnow


class Notification(Base):
    """In-app notification for ONE user. Rows are best-effort: generating them must never break the main flow."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", text("created_at DESC")),
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(512))
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # noqa: F821


class HighRiskAlert(Base):
    """One durable, deduplicated alert per high-risk assessment (detection ID)."""

    __tablename__ = "high_risk_alerts"
    __table_args__ = (
        UniqueConstraint("assessment_id", name="uq_high_risk_alert_assessment"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_range"),
        Index("ix_high_risk_alerts_entity_created", "entity_id", text("created_at DESC")),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_assessments.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("digital_entities.id", ondelete="CASCADE"), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)


class PasswordResetToken(Base):
    """Single-use password-reset token. Only the SHA-256 hash of the token is stored."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_tokens_user", "user_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = tz_col(nullable=False)
    used_at: Mapped[datetime | None] = tz_col()
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # noqa: F821
