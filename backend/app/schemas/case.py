from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import CaseEventType, CaseStatus, PartnerType, ResolutionOutcome, Severity
from app.schemas.common import ORM
from app.schemas.detection import AssessmentOut
from app.schemas.entity import EntityOut
from app.schemas.evidence import EvidenceOut

# Platform keys (must stay in sync with the frontend's PLATFORM_LABELS keys)
CasePlatform = Literal[
    "x", "twitter", "instagram", "facebook", "tiktok", "youtube",
    "google_play", "app_store", "linkedin", "reddit", "web", "other",
]


class CaseCreate(BaseModel):
    brand_id: uuid.UUID
    title: str = Field(min_length=3, max_length=300)
    summary: str | None = Field(None, max_length=10000)
    entity_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    platforms: list[CasePlatform] = Field(default_factory=list, max_length=20, description="Platforms this case spans")


class CaseStatusUpdate(BaseModel):
    status: CaseStatus
    expected_status: CaseStatus | None = Field(None, description="If set, the update is rejected with 409 unless the case is currently in this status (duplicate/race protection)")
    comment: str | None = Field(None, max_length=5000)
    resolution_outcome: ResolutionOutcome | None = None
    resolution_summary: str | None = Field(None, max_length=10000)


class CaseAssign(BaseModel):
    assignee_id: uuid.UUID
    note: str | None = Field(None, max_length=2000)


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class EscalateRequest(BaseModel):
    partner_type: PartnerType
    partner_contact: str | None = Field(None, max_length=300)
    reason: str = Field(min_length=5, max_length=5000)
    requested_action: str | None = Field(None, max_length=2000)


class ResolveRequest(BaseModel):
    outcome: ResolutionOutcome
    summary: str = Field(min_length=5, max_length=10000)


class CaseEntityLink(BaseModel):
    entity_id: uuid.UUID
    role: str = Field("related", pattern=r"^(subject|related)$")


class UserRef(ORM):
    id: uuid.UUID
    email: str
    full_name: str


class NoteOut(ORM):
    id: uuid.UUID
    case_id: uuid.UUID
    author: UserRef | None = None
    body: str
    created_at: datetime


class EventOut(ORM):
    id: uuid.UUID
    case_id: uuid.UUID
    event_type: CaseEventType
    from_status: CaseStatus | None
    to_status: CaseStatus | None
    actor: UserRef | None = None
    details: dict[str, Any]
    created_at: datetime


class EscalationOut(ORM):
    id: uuid.UUID
    partner_type: PartnerType
    partner_contact: str | None
    reason: str
    requested_action: str | None
    created_by_id: uuid.UUID | None
    created_at: datetime


class AssignmentOut(ORM):
    id: uuid.UUID
    assignee: UserRef | None = None
    assigned_by_id: uuid.UUID | None
    assigned_at: datetime
    unassigned_at: datetime | None
    note: str | None


class CaseSummary(ORM):
    id: uuid.UUID
    case_number: str
    brand_id: uuid.UUID
    title: str
    status: CaseStatus
    severity: Severity
    confidence: float | None
    risk_score: float | None
    assigned_to: UserRef | None = None
    entity_count: int = 0
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class CaseEntityDetail(BaseModel):
    role: str
    entity: EntityOut
    latest_assessment: AssessmentOut | None
    evidence: list[EvidenceOut]


class CaseEvidenceOut(EvidenceOut):
    role: str = "supporting"


class CasePatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=300)
    summary: str | None = Field(None, max_length=10000)
    severity: Severity | None = None
    platforms: list[CasePlatform] | None = Field(None, max_length=20, description="Replace the case's platform tags")
    version: int | None = Field(None, ge=1, description="Optimistic concurrency: 409 if it no longer matches the stored version")


class CaseDetail(CaseSummary):
    summary: str | None
    cluster_key: str | None
    platforms: list[CasePlatform] = []
    risk_assessment: AssessmentOut | None
    escalated_at: datetime | None
    escalation_summary: str | None
    resolution_outcome: ResolutionOutcome | None
    resolution_summary: str | None
    resolved_by: UserRef | None = None
    created_by: UserRef | None = None
    entities: list[CaseEntityDetail]
    evidence: list[CaseEvidenceOut] = []
    notes: list[NoteOut]
    events: list[EventOut]
    escalations: list[EscalationOut]
    assignments: list[AssignmentOut]
    allowed_transitions: list[CaseStatus]
    version: int
