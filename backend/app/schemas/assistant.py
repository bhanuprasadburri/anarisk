from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    entity_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None


class AssistantCitation(BaseModel):
    type: str
    id: str
    title: str


class AssistantAskResponse(BaseModel):
    answer: str
    cited: list[AssistantCitation] = []
    used_ai: bool = False
    provider: str = "none"
    model: str = ""
    unsupported_citations: list[str] = []
    limitation: str = ""
