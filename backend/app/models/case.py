from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_col, tz_col, uuid_pk, utcnow
from app.models.enums import CaseEventType, CaseStatus, PartnerType, ResolutionOutcome, ResponseOutcome, Severity


class InvestigationCase(TimestampMixin, Base):
    __tablename__ = "investigation_cases"
    __table_args__ = (
        Index("ix_cases_brand_status", "brand_id", "status"),
        Index("ix_cases_assignee", "assigned_to_id"),
        Index("ix_cases_response_outcome", "response_outcome"),
        CheckConstraint("risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 1)", name="risk_range"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        CheckConstraint(
            "response_outcome <> 'removal_observed' OR response_evidence_id IS NOT NULL",
            name="ck_case_removal_evidence",
        ),
        UniqueConstraint("created_by_id", "idempotency_key", name="uq_cases_creator_idempotency"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CaseStatus] = mapped_column(enum_col(CaseStatus, "case_status"), default=CaseStatus.DETECTED, nullable=False)
    severity: Mapped[Severity] = mapped_column(enum_col(Severity, "severity"), default=Severity.UNKNOWN, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("risk_assessments.id", ondelete="SET NULL"))
    cluster_key: Mapped[str | None] = mapped_column(String(64), index=True)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    escalated_at: Mapped[datetime | None] = tz_col()
    escalation_summary: Mapped[str | None] = mapped_column(Text)
    resolution_outcome: Mapped[ResolutionOutcome | None] = mapped_column(enum_col(ResolutionOutcome, "resolution_outcome"))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = tz_col()
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Round 2 §7: the operational response to a threat, tracked separately from the analytical disposition.
    # "removal_observed" is only valid with verification evidence (enforced by _ck_case_removal_evidence + service check).
    response_outcome: Mapped[ResponseOutcome | None] = mapped_column(enum_col(ResponseOutcome, "response_outcome"))
    response_outcome_at: Mapped[datetime | None] = tz_col()
    response_outcome_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    response_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="SET NULL")
    )  # proof of removal (required when response_outcome == removal_observed)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Platforms this case spans (values validated against PLATFORM_LABELS keys at the API layer)
    platforms: Mapped[list[Any]] = mapped_column(default=list, nullable=False, server_default=text("'[]'"))

    brand: Mapped["Brand"] = relationship(lazy="joined")  # noqa: F821
    assigned_to: Mapped["User | None"] = relationship(foreign_keys=[assigned_to_id], lazy="joined")  # noqa: F821
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])  # noqa: F821
    resolved_by: Mapped["User | None"] = relationship(foreign_keys=[resolved_by_id])  # noqa: F821
    entities: Mapped[list[CaseEntity]] = relationship(back_populates="case", cascade="all, delete-orphan")
    assignments: Mapped[list[CaseAssignment]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="CaseAssignment.assigned_at")
    notes: Mapped[list[CaseNote]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="CaseNote.created_at")
    events: Mapped[list[CaseEvent]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="CaseEvent.created_at")
    escalations: Mapped[list[CaseEscalation]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="CaseEscalation.created_at")

    @property
    def entity_count(self) -> int:
        return len(self.entities)


class CaseEntity(Base):
    __tablename__ = "case_entities"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("digital_entities.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="subject", nullable=False)  # subject | related
    added_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    case: Mapped[InvestigationCase] = relationship(back_populates="entities")
    entity: Mapped["DigitalEntity"] = relationship()  # noqa: F821


class CaseEvidenceLink(Base):
    """Evidence attached directly to a case (case detail page)."""

    __tablename__ = "case_evidence"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_records.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="supporting", nullable=False)
    added_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    case: Mapped[InvestigationCase] = relationship()
    evidence: Mapped["EvidenceRecord"] = relationship()  # noqa: F821


class CaseAssignment(Base):
    """Assignment history. The open row (unassigned_at IS NULL) is the current owner."""

    __tablename__ = "case_assignments"
    __table_args__ = (
        Index("uq_case_assignments_one_open", "case_id", unique=True, postgresql_where="unassigned_at IS NULL"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), index=True, nullable=False)
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)
    unassigned_at: Mapped[datetime | None] = tz_col()
    note: Mapped[str | None] = mapped_column(Text)

    assignee: Mapped["User"] = relationship(foreign_keys=[assignee_id])  # noqa: F821
    case: Mapped[InvestigationCase] = relationship(back_populates="assignments")


class CaseNote(Base):
    __tablename__ = "case_notes"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), index=True, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)

    author: Mapped["User | None"] = relationship(foreign_keys=[author_id])  # noqa: F821
    case: Mapped[InvestigationCase] = relationship(back_populates="notes")


class CaseEvent(Base):
    """Append-only status/activity history."""

    __tablename__ = "case_events"
    __table_args__ = (Index("ix_case_events_case_time", "case_id", "created_at"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[CaseEventType] = mapped_column(enum_col(CaseEventType, "case_event_type"), nullable=False)
    from_status: Mapped[CaseStatus | None] = mapped_column(enum_col(CaseStatus, "case_event_from_status"))
    to_status: Mapped[CaseStatus | None] = mapped_column(enum_col(CaseStatus, "case_event_to_status"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)

    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id])  # noqa: F821
    case: Mapped[InvestigationCase] = relationship(back_populates="events")


class CaseEscalation(Base):
    """Partner handoff record (legal / marketing / platform contact)."""

    __tablename__ = "case_escalations"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"), index=True, nullable=False)
    partner_type: Mapped[PartnerType] = mapped_column(enum_col(PartnerType, "partner_type"), nullable=False)
    partner_contact: Mapped[str | None] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_action: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = tz_col(default=utcnow, nullable=False)

    case: Mapped[InvestigationCase] = relationship(back_populates="escalations")


from sqlalchemy import Sequence  # noqa: E402

from app.models.base import Base as _Base  # noqa: E402

# Human-readable case numbers: NN-<year>-<6 digit sequence>. Created in the migration.
case_number_seq = Sequence("case_number_seq", metadata=_Base.metadata)
