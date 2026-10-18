"""AI Investigation Assistant (chat over authorized records with citations)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.assistant import AssistantAskRequest, AssistantAskResponse, AssistantCitation
from app.services import assistant as assistant_svc
from app.services.ai.providers import provider_status

router = APIRouter(prefix="/assistant", tags=["AI Assistant"])


@router.post("/ask", response_model=AssistantAskResponse,
             dependencies=[Depends(require_permission("entity:read")),
                           Depends(rate_limit("assistant_ask", "analyze_rate_limit_per_minute"))],
             summary="Ask a question about your records. Answers cite retrieved record ids; "
                     "uses the configured AI provider or deterministic retrieval when none is set.")
def ask(body: AssistantAskRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = assistant_svc.assistant_answer(db, user, body.question, entity_id=body.entity_id, case_id=body.case_id)
    return AssistantAskResponse(
        answer=result.answer,
        cited=[AssistantCitation(**c) for c in result.cited],
        used_ai=result.used_ai, provider=result.provider, model=result.model,
        unsupported_citations=result.unsupported_citations, limitation=result.limitation,
    )


@router.get("/status", summary="AI provider status (honest: never claims a provider that is not configured)",
            tags=["AI Assistant"])
def status(user: User = Depends(require_permission("entity:read"))):
    return provider_status()
