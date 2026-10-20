from __future__ import annotations

from app.services import phishtank


class _Response:
    status_code = 200

    def json(self):
        return {"results": {"url": {"in_database": True, "verified": "y", "valid": "y", "phish_id": 123}}}


def test_lookup_requires_backend_key_before_external_request(monkeypatch):
    monkeypatch.setattr(phishtank.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert phishtank.lookup("https://example.com", "")["status"] == "unavailable"


def test_lookup_returns_match_and_caches_hashed_indicator(monkeypatch):
    phishtank._cache.clear()
    phishtank._last_request = 0
    calls = []
    monkeypatch.setattr(phishtank.httpx, "post", lambda *a, **k: (calls.append(a) or _Response()))
    assert phishtank.lookup("https://example.com/path", "test-key")["status"] == "confirmed_match"
    assert all("example.com" not in key for key in phishtank._cache)
    assert phishtank.lookup("https://example.com/path", "test-key")["cached"] is True
    assert len(calls) == 1


def test_lookup_reports_provider_failure(monkeypatch):
    phishtank._cache.clear()
    phishtank._last_request = 0
    monkeypatch.setattr(phishtank.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert phishtank.lookup("https://example.net", "test-key")["status"] == "error"
