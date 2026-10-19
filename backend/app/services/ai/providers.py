"""AI providers: none | memory (tests) | openai-compatible.

The OpenAI-compatible provider works with any service that implements the
``POST {base}/chat/completions`` contract (OpenAI, Azure OpenAI-compatible gateways,
Ollama, vLLM, LiteLLM, ...). Configuration comes from environment variables only.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.core.config import get_settings
from app.services.ai.base import AIProviderError

log = logging.getLogger(__name__)


class BaseProvider:
    name = "base"

    def complete_json(self, system: str, user: str, *, max_tokens: int | None = None) -> dict:
        raise NotImplementedError

    def complete_image_json(self, system: str, user: str, image_b64: str, mime: str,
                            *, max_tokens: int | None = None) -> dict:
        """Structured JSON completion with ONE attached image (multimodal).

        The default refuses honestly rather than pretending the image was seen.
        """
        raise AIProviderError(f"provider '{self.name}' does not support image input")


class MemoryProvider(BaseProvider):
    """Test/dev provider: performs NO model inference and invents nothing.

    It returns a strictly mechanical summary of the context it was given, which lets the
    whole grounding/citation pipeline be exercised deterministically.
    """

    name = "memory"

    def complete_json(self, system: str, user: str, *, max_tokens: int | None = None) -> dict:
        # Pull the record ids out of the UNTRUSTED_DATA block so citations stay grounded.
        ids: list[str] = []
        marker = 'records="'
        if marker in user:
            raw = user.split(marker, 1)[1].split('"', 1)[0]
            ids = [i.strip() for i in raw.split(",") if i.strip()]
        findings = [{"title": f"Retrieved context: {rid}", "detail": "Records matched your question and are listed with their ids.",
                     "evidence_ids": [rid], "kind": "verified_fact"} for rid in ids[:3]]
        return {
            "input_type": "assistant_question",
            "subject": "Record retrieval summary",
            "findings": findings,
            "verified_facts": [f"{len(ids)} authorized record(s) matched the question."],
            "inferences": [],
            "missing_information": ["No AI model is configured - add AI_API_KEY and set AI_PROVIDER=openai-compatible for model-assisted interpretation."],
            "limitations": ["This answer was produced by deterministic retrieval, not a language model."],
            "recommended_next_steps": ["Open the cited records and review them directly."],
            "severity": "unknown",
            "evidence_strength": "moderate",
            "model": "memory-retrieval-only",
            "provider": "memory",
        }

    def complete_image_json(self, system: str, user: str, image_b64: str, mime: str,
                            *, max_tokens: int | None = None) -> dict:
        """Deterministic receipt of an image payload: no inference, invents nothing."""
        return {
            "findings": [],
            "observations": [f"{mime} image payload of {len(image_b64)} base64 characters received."],
            "limitations": ["No model inference was performed (memory provider) — the image content was NOT interpreted."],
            "model": "memory-retrieval-only",
            "provider": "memory",
        }


class OpenAICompatibleProvider(BaseProvider):
    name = "openai-compatible"

    def complete_json(self, system: str, user: str, *, max_tokens: int | None = None) -> dict:
        s = get_settings()
        if not s.ai_api_key or not s.ai_model:
            raise AIProviderError("AI provider is not configured (AI_API_KEY / AI_MODEL missing)")
        try:
            resp = httpx.post(
                f"{s.ai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {s.ai_api_key}", "Content-Type": "application/json"},
                json={
                    "model": s.ai_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_tokens or s.ai_max_tokens,
                },
                timeout=s.ai_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"AI provider timed out after {s.ai_timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"AI provider request failed: {type(exc).__name__}") from exc
        if resp.status_code in (401, 403):
            raise AIProviderError("AI provider rejected the credentials (check AI_API_KEY)")
        if resp.status_code == 429:
            raise AIProviderError("AI provider rate limit or quota exceeded")
        if resp.status_code >= 400:
            raise AIProviderError(f"AI provider returned HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"AI provider returned an unusable response ({type(exc).__name__})") from exc

    def complete_image_json(self, system: str, user: str, image_b64: str, mime: str,
                            *, max_tokens: int | None = None) -> dict:
        s = get_settings()
        if not s.ai_api_key or not s.ai_model:
            raise AIProviderError("AI provider is not configured (AI_API_KEY / AI_MODEL missing)")
        try:
            resp = httpx.post(
                f"{s.ai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {s.ai_api_key}", "Content-Type": "application/json"},
                json={
                    "model": s.ai_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": [
                            {"type": "text", "text": user},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        ]},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_tokens or s.ai_max_tokens,
                },
                timeout=s.ai_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"AI provider timed out after {s.ai_timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"AI provider request failed: {type(exc).__name__}") from exc
        if resp.status_code in (401, 403):
            raise AIProviderError("AI provider rejected the credentials (check AI_API_KEY)")
        if resp.status_code == 429:
            raise AIProviderError("AI provider rate limit or quota exceeded")
        if resp.status_code >= 400:
            raise AIProviderError(f"AI provider returned HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"AI provider returned an unusable response ({type(exc).__name__})") from exc


def get_provider() -> BaseProvider | None:
    s = get_settings()
    if s.ai_provider == "memory":
        return MemoryProvider()
    if s.ai_provider == "openai-compatible":
        if not s.ai_api_key or not s.ai_model:
            log.warning("AI_PROVIDER=openai-compatible but AI_API_KEY/AI_MODEL are missing - AI features are unavailable")
            return None
        return OpenAICompatibleProvider()
    return None


def provider_status() -> dict:
    s = get_settings()
    configured = get_provider() is not None
    return {
        "provider": s.ai_provider,
        "model": s.ai_model or None,
        "configured": configured,
        "note": ("No AI provider is configured: answers are produced by deterministic retrieval over your records "
                 "and are labelled as such." if not configured
                 else "AI-assisted answers cite retrieved record ids; model output is validated and never executed."),
    }
