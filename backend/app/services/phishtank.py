"""Opt-in PhishTank URL lookups; provider results never modify AnaRisk risk scores."""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime

import httpx

ENDPOINT = "https://checkurl.phishtank.com/checkurl/"
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_last_request = 0.0
_CACHE_TTL_SECONDS = 300
_MIN_INTERVAL_SECONDS = 1.0


def lookup(raw_url: str, app_key: str) -> dict:
    from app.services.tools.url_analyzer import parse_url

    checked_at = datetime.now(UTC).isoformat()
    parsed = parse_url(raw_url)
    if parsed is None:
        return {"status": "invalid_input", "source": "PhishTank", "checked_at": checked_at}
    if not app_key:
        return {"status": "unavailable", "reason": "provider_not_configured", "source": "PhishTank", "checked_at": checked_at}
    key = parsed.canonical
    cache_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
    global _last_request
    now = time.monotonic()
    with _lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return {**cached[1], "cached": True}
        if now - _last_request < _MIN_INTERVAL_SECONDS:
            return {"status": "rate_limited", "source": "PhishTank", "checked_at": checked_at}
        _last_request = now
    payload = {"url": key, "format": "json", "app_key": app_key}
    headers = {"User-Agent": "AnaRisk/1.0 phishing-indicator-check"}
    try:
        response = httpx.post(ENDPOINT, data=payload, headers=headers, timeout=4.0, follow_redirects=False)
        if response.status_code >= 500 and response.status_code != 509:
            response = httpx.post(ENDPOINT, data=payload, headers=headers, timeout=4.0, follow_redirects=False)
        if response.status_code == 509:
            result = {"status": "rate_limited", "source": "PhishTank", "checked_at": checked_at}
        elif response.status_code >= 400:
            result = {"status": "error", "reason": "provider_http_error", "source": "PhishTank", "checked_at": checked_at}
        else:
            data = response.json()
            item = data.get("results", {}).get("url", {}) if isinstance(data, dict) else {}
            if not isinstance(item, dict) or not isinstance(item.get("in_database"), bool):
                raise ValueError("unexpected provider response")
            verified = str(item.get("verified", "")).lower() in {"true", "y", "yes"}
            valid = str(item.get("valid", "")).lower() in {"true", "y", "yes"}
            confirmed = item["in_database"] and verified and valid
            status = "confirmed_match" if confirmed else ("unable_to_verify" if item["in_database"] else "no_match")
            result = {
                "status": status, "source": "PhishTank", "checked_at": checked_at,
                "verified_at": item.get("verified_at") if confirmed else None,
                "phish_id": str(item.get("phish_id"))[:32] if confirmed and item.get("phish_id") else None,
                "limitation": "No match means only that PhishTank did not confirm this URL at lookup time; it is not proof of safety.",
            }
        if result["status"] in {"confirmed_match", "no_match"}:
            with _lock:
                _cache[cache_key] = (time.monotonic(), result)
                if len(_cache) > 512:
                    _cache.pop(next(iter(_cache)))
        return result
    except Exception:
        return {"status": "error", "reason": "provider_unavailable", "source": "PhishTank", "checked_at": checked_at}
