from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Severity, SignalStatus, SignalType
from app.schemas.common import ORM


class DetectionEntityRef(BaseModel):
    id: uuid.UUID
    display_name: str
    entity_type: str
    canonical_id: str
    platform: str | None = None
    provenance: str
    # Round 2 §2 "complete detection record": observation window + where it was seen
    source_url: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class SignalOut(ORM):
    id: uuid.UUID
    entity_id: uuid.UUID
    assessment_id: uuid.UUID
    signal_type: SignalType
    status: SignalStatus
    score: float | None
    explanation: str
    evidence_refs: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    # joined-in entity context so signal listings can show which asset fired (None when unknown)
    entity: DetectionEntityRef | None = None


class AssessmentOut(ORM):
    id: uuid.UUID
    entity_id: uuid.UUID
    model_version: str
    configured_weights: dict[str, float]
    effective_weights: dict[str, float]
    component_scores: dict[str, float | None]
    risk_score: float | None
    confidence_score: float
    confidence_breakdown: dict[str, Any]
    severity: Severity
    thresholds: dict[str, float]
    is_synthetic: bool
    notes: str | None
    assessed_at: datetime
    signals: list[SignalOut] = []


class BulkAnalyzeRequest(BaseModel):
    entity_ids: list[uuid.UUID] | None = Field(None, max_length=200)
    brand_id: uuid.UUID | None = None


class BulkAnalyzeResult(BaseModel):
    analyzed: int
    skipped: list[dict[str, Any]]
    assessments: list[AssessmentOut]


class RuleDescription(BaseModel):
    """Plain-English description of the ACTUAL heuristics implemented in app/services/detection/*.py."""

    signal_type: str
    label: str
    rules: str


class ModelInfo(BaseModel):
    model_version: str
    weights: dict[str, float]
    severity_thresholds: dict[str, float]
    confidence: dict[str, Any]
    rule_description: list[RuleDescription] = []
    status: str = "heuristic - unvalidated; requires human review"


class SignalSummary(BaseModel):
    signal_type: SignalType
    status: SignalStatus
    score: float | None = None


class DetectionItem(BaseModel):
    """Flattened latest assessment per entity for the Detections list."""

    id: uuid.UUID  # assessment id
    entity: DetectionEntityRef
    detection_type: str  # plain-English label of the highest-weight signal
    signal_type: SignalType | None = None
    risk_score: float | None
    confidence: float
    severity: Severity
    status: str  # analyzed | partial | unavailable (derived from signal availability)
    explanation: str = ""
    signals_summary: list[SignalSummary] = []
    # Round 2 §2: the official asset this detection was measured against (from the top logo/impersonation match)
    matched_official_asset_id: uuid.UUID | None = None
    assessed_at: datetime
    is_synthetic: bool


class DetectionDetail(AssessmentOut):
    """Full assessment (same shape as /detection/assessments/{id}) plus an honest message."""

    message: str | None = None
