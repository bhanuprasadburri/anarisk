"""AI Investigation Assistant.

Answers questions about the records the *authenticated user is authorized to see*:

1. retrieve matching entities/cases/evidence/analyses (org-scoped, via the same predicates
   used by the main APIs),
2. hand them to the configured AI provider as explicitly untrusted, delimited data,
3. validate the model's JSON output and drop any citation that is not one of the records
   we actually provided.

When no AI provider is configured the assistant still works - it answers with the retrieved
records themselves and says plainly that no model was involved. It never guesses.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.models import DigitalEntity, EvidenceRecord, InvestigationCase, ToolAnalysis, User
from app.repositories.access import brand_scope
from app.services.ai.base import (
    AIAnswer, AIProviderError, AIStructuredAnalysis, INJECTION_GUARD, UNTRUSTED_WRAPPER, ContextRecord,
)
from app.services.ai.providers import get_provider
from app.services.ai.prompts import SYSTEM_PROMPT
from app.models.enums import Severity

log = logging.getLogger(__name__)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "what", "why", "how", "does", "do", "did", "this", "that",
    "these", "those", "it", "its", "of", "for", "to", "in", "on", "and", "or", "we", "you", "i", "me", "my",
    "our", "us", "can", "could", "should", "would", "tell", "about", "from", "with", "at", "be", "there", "here",
}
MAX_CONTEXT_RECORDS = 25


def _keywords(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9@._-]{3,}", question.lower())
    return [w for w in dict.fromkeys(words) if w not in _STOPWORDS][:12]


# Severity words are meaningful filters, not searchable keywords: "which entities are critical"
# should narrow by severity rather than fail to match any display name.
_SEVERITY_WORDS = {s.value for s in Severity}


def _severity_filter(question: str) -> Severity | None:
    """Detect an explicit severity qualifier in the question, if any."""
    q = question.lower()
    for word in ("critical", "high", "medium", "low"):
        if re.search(rf"\b{word}\b", q):
            return Severity(word)
    return None


def retrieve(db: Session, user: User, question: str, *, entity_id=None, case_id=None) -> list[ContextRecord]:
    """Keyword retrieval over the records this user may access. No cross-org rows, ever."""
    kws = _keywords(question)
    severity = _severity_filter(question)
    if severity is not None:
        # A severity qualifier is a filter, not a search term.
        kws = [k for k in kws if k not in _SEVERITY_WORDS]
    out: list[ContextRecord] = []
    scope_pred = brand_scope(user, DigitalEntity.brand_id)

    # explicit focus records first
    if entity_id is not None:
        e = db.scalar(select(DigitalEntity).where(DigitalEntity.id == entity_id, scope_pred))
        if e is not None:
            out.append(_entity_record(e))
    if case_id is not None:
        c = db.scalar(select(InvestigationCase).where(InvestigationCase.id == case_id,
                                                      brand_scope(user, InvestigationCase.brand_id)))
        if c is not None:
            out.append(_case_record(c))

    if kws and len(out) < MAX_CONTEXT_RECORDS:
        like = [f"%{k}%" for k in kws]
        entity_rows = db.scalars(
            select(DigitalEntity).where(scope_pred, or_(*[
                or_(DigitalEntity.display_name.ilike(l), DigitalEntity.canonical_id.ilike(l)) for l in like
            ])).limit(8)
        ).all()
        out.extend(_entity_record(e) for e in entity_rows)
        case_rows = db.scalars(
            select(InvestigationCase).where(
                brand_scope(user, InvestigationCase.brand_id),
                or_(InvestigationCase.title.ilike(f"%{kws[0]}%"), InvestigationCase.case_number.ilike(f"%{kws[0]}%")),
            ).limit(6)
        ).all()
        out.extend(_case_record(c) for c in case_rows)
        # evidence: org-scoped through its entity's brand
        ev_conditions = []
        for l in like[:4]:
            ev_conditions.append(EvidenceRecord.title.ilike(l))
            ev_conditions.append(EvidenceRecord.source_url.ilike(l))
        ev_rows = db.scalars(
            select(EvidenceRecord).join(DigitalEntity, DigitalEntity.id == EvidenceRecord.entity_id)
            .where(scope_pred, or_(*ev_conditions)).limit(6)
        ).all()
        out.extend(_evidence_record(v) for v in ev_rows)
        if user.organization_id is not None:
            tool_conditions = [ToolAnalysis.subject.ilike(l) for l in like[:4]]
            tool_rows = db.scalars(
                select(ToolAnalysis).where(
                    ToolAnalysis.organization_id == user.organization_id, or_(*tool_conditions)
                ).limit(4)
            ).all()
            out.extend(_tool_record(t) for t in tool_rows)

    # A severity-only question ("which entities are critical?") has no name keywords to match,
    # so it is answered by filtering on the computed severity directly.
    if severity is not None and not any(r.record_type == "entity" for r in out) and len(out) < MAX_CONTEXT_RECORDS:
        sev_rows = db.scalars(
            select(DigitalEntity).where(scope_pred, DigitalEntity.current_severity == severity)
            .order_by(DigitalEntity.current_risk_score.desc().nullslast()).limit(8)
        ).all()
        out.extend(_entity_record(e) for e in sev_rows)

    dedup: dict[tuple[str, str], ContextRecord] = {(r.record_type, r.record_id): r for r in out}
    return list(dedup.values())[:MAX_CONTEXT_RECORDS]


def _entity_record(e: DigitalEntity) -> ContextRecord:
    return ContextRecord(
        "entity", str(e.id), e.display_name or e.canonical_id,
        f"{e.entity_type.value} entity, risk={e.current_risk_score}, severity={e.current_severity.value}, "
        f"provenance={e.provenance.value}, canonical_id={e.canonical_id}",
    )


def _case_record(c: InvestigationCase) -> ContextRecord:
    return ContextRecord(
        "case", str(c.id), c.title,
        f"case {c.case_number}, status={c.status.value}, severity={c.severity.value}",
    )


def _evidence_record(v: EvidenceRecord) -> ContextRecord:
    return ContextRecord(
        "evidence", str(v.id), v.title or "(untitled evidence)",
        f"{v.kind.value} evidence, provenance={v.provenance.value}, sha256={'yes' if v.sha256 else 'no'}, "
        f"entity={v.entity_id}",
    )


def _tool_record(t: ToolAnalysis) -> ContextRecord:
    return ContextRecord(
        "tool_analysis", str(t.id), t.subject,
        f"{t.tool} analysis, severity={t.severity}, risk={t.risk_score}, findings={len(t.findings or [])}",
    )


def assistant_answer(
    db: Session, user: User, question: str, *, entity_id=None, case_id=None
) -> AIAnswer:
    records = retrieve(db, user, question, entity_id=entity_id, case_id=case_id)
    provider = get_provider()
    if not records:
        return AIAnswer(
            answer=("I could not find any records in your workspace that match this question. "
                    "Try including a name, domain, handle, case number, or run a scan first."),
            cited=[], used_ai=False, limitation="No matching authorized records were retrieved.",
        )
    if provider is None:
        lines = [f"• [{r.record_type}:{r.record_id}] {r.title} — {r.summary}" for r in records]
        return AIAnswer(
            answer=("Here are the records in your workspace that match your question "
                    "(deterministic retrieval — no AI model is configured on this deployment):\n\n"
                    + "\n".join(lines)),
            cited=[{"type": r.record_type, "id": r.record_id, "title": r.title} for r in records],
            used_ai=False, limitation="No AI provider configured (AI_PROVIDER=none). This is raw retrieval, not model analysis.",
        )

    ids = ",".join(f"{r.record_type}:{r.record_id}" for r in records)
    payload = "\n\n".join(
        f"[{r.record_type}:{r.record_id}] {r.title}\n{r.summary}" for r in records
    )
    user_msg = UNTRUSTED_WRAPPER.format(ids=ids, payload=payload) + f"\nQUESTION: {question[:2000]}\n\n{INJECTION_GUARD}"
    try:
        raw = provider.complete_json(SYSTEM_PROMPT, user_msg)
        analysis = AIStructuredAnalysis.model_validate(raw)
    except (AIProviderError, ValidationError) as exc:
        log.warning("AI assistant failed (%s) - falling back to deterministic retrieval", exc)
        lines = [f"• [{r.record_type}:{r.record_id}] {r.title} — {r.summary}" for r in records]
        return AIAnswer(
            answer=("The AI provider could not answer right now (see limitation below). "
                    "Here are the matching records from deterministic retrieval:\n\n" + "\n".join(lines)),
            cited=[{"type": r.record_type, "id": r.record_id, "title": r.title} for r in records],
            used_ai=False, limitation=f"AI provider error: {exc}",
        )

    allowed = {f"{r.record_type}:{r.record_id}" for r in records}
    cited: list[dict[str, str]] = []
    dropped: list[str] = []
    for f in analysis.findings:
        for cid in f.evidence_ids:
            cid = cid.strip()
            if cid in allowed and cid not in [c["type"] + ":" + c["id"] for c in cited]:
                rtype, rid = cid.split(":", 1)
                title = next((r.title for r in records if str(r.record_id) == rid), "")
                cited.append({"type": rtype, "id": rid, "title": title})
            elif cid not in allowed:
                dropped.append(cid)
    answer = _render(analysis)
    if dropped:
        answer += f"\n\n_(Note: {len(dropped)} model citation(s) did not match retrieved records and were removed.)_"
    return AIAnswer(
        answer=answer, cited=cited, used_ai=True, provider=provider.name, model=analysis.model,
        unsupported_citations=dropped,
        limitation="AI-assisted summary. Every claim should be checked against the cited records; "
                   "model confidence is not a calibrated probability.",
    )


def _render(a: AIStructuredAnalysis) -> str:
    parts: list[str] = [f"## {a.subject}", ""]
    if a.verified_facts:
        parts.append("**Verified facts (from records):**")
        parts.extend(f"- {v}" for v in a.verified_facts)
        parts.append("")
    if a.findings:
        parts.append("**Findings:**")
        for f in a.findings:
            tag = "fact" if f.kind == "verified_fact" else "inference"
            cites = (" [" + ", ".join(f.evidence_ids) + "]") if f.evidence_ids else ""
            parts.append(f"- ({tag}) {f.title}: {f.detail}{cites}")
        parts.append("")
    if a.inferences:
        parts.append("**Inferences (analytical, not verified):**")
        parts.extend(f"- {i}" for i in a.inferences)
        parts.append("")
    if a.missing_information:
        parts.append("**Missing before a conclusion:**")
        parts.extend(f"- {m}" for m in a.missing_information)
        parts.append("")
    if a.limitations:
        parts.append("**Limitations:**")
        parts.extend(f"- {l}" for l in a.limitations)
        parts.append("")
    if a.recommended_next_steps:
        parts.append("**Suggested next steps:**")
        parts.extend(f"- {s}" for s in a.recommended_next_steps)
        parts.append("")
    parts.append(f"_Evidence strength (model's own assessment): {a.evidence_strength}; "
                 f"model: {a.provider}/{a.model}._")
    return "\n".join(parts)


def dump_context(records: list[ContextRecord]) -> str:
    return json.dumps([r.__dict__ for r in records], indent=2)
