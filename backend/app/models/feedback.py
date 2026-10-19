from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_col, uuid_pk
from app.models.enums import FeedbackCategory, FeedbackStatus


class Feedback(TimestampMixin, Base):
    """User-submitted feedback (bugs, feature requests, content issues, other).

    `organization_id` / `brand_id` are snapshotted from the submitter's scope at submission
    time, so the authorized admin view stays correct even if memberships change later.
    `related_case_id` is optional and only accepted when the submitter can already read it.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_org_created", "organization_id", text("created_at DESC")),
        Index("ix_feedback_status_created", "status", text("created_at DESC")),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))
    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    category: Mapped[FeedbackCategory] = mapped_column(enum_col(FeedbackCategory, "feedback_category"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    page_ref: Mapped[str | None] = mapped_column(String(500))
    related_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="SET NULL")
    )
    status: Mapped[FeedbackStatus] = mapped_column(
        enum_col(FeedbackStatus, "feedback_status"), default=FeedbackStatus.OPEN, nullable=False
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # noqa: F821
    brand: Mapped["Brand | None"] = relationship(foreign_keys=[brand_id])  # noqa: F821
