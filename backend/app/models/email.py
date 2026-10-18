from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, tz_col, uuid_pk, utcnow


class EmailVerificationToken(Base):
    """Single-use email-verification credential (6-digit OTP for signup verification).

    Only an HMAC-SHA256 hash (keyed with SECRET_KEY) of the OTP is stored — never the
    code itself — plus expiry and the wrong-attempt counter used for lockout.
    """

    __tablename__ = "email_verification_tokens"
    __table_args__ = (Index("ix_email_verification_tokens_user", "user_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = tz_col(nullable=False)
    used_at: Mapped[datetime | None] = tz_col()
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # noqa: F821


class EmailDeliveryLog(Base):
    """One row per attempted outbound email. Records the honest outcome of every delivery attempt."""

    __tablename__ = "email_delivery_logs"
    __table_args__ = (Index("ix_email_delivery_logs_created", "created_at"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # sent | failed | skipped (dev fallback: no provider configured)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)
