from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, tz_col, uuid_pk, utcnow


class ToolAnalysis(Base):
    """Persisted result of an on-demand investigation tool run (email, job offer, social profile, URL).

    `findings` is a JSONB list of finding dicts, each carrying its own status
    (verified | suspicious | inconclusive | unable_to_verify | info), severity, evidence and
    limitation text. `input_summary` stores a truncated, sanitized copy of the submitted input
    (never raw attachments or full email bodies beyond the stored limit).
    """

    __tablename__ = "tool_analyses"
    __table_args__ = (
        Index("ix_tool_analyses_org_created", "organization_id", "created_at"),
        Index("ix_tool_analyses_org_tool", "organization_id", "tool"),
        CheckConstraint("tool IN ('email', 'job_offer', 'social_profile', 'url', 'image')", name="tool_values"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    tool: Mapped[str] = mapped_column(String(32), nullable=False)  # email | job_offer | social_profile | url
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    input_summary: Mapped[dict[str, Any] | None] = mapped_column(default=None)  # JSONB
    findings: Mapped[list[Any]] = mapped_column(default=list)  # JSONB list of finding dicts
    risk_score: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    methodology_version: Mapped[str] = mapped_column(String(32), default="tools-v1", nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("digital_entities.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)
