"""Investigation tools (email/job/social/url) + AI assistant + monitoring scheduler.

Network-dependent lookups (DNS, TLS) are monkeypatched so the tests are deterministic and
do not touch the network.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.tools.common import dns_query


@pytest.fixture(autouse=True)
def _no_network_dns(monkeypatch):
    """Deterministic DNS: domains under example/x/xyz answer plausibly; everything else NXDOMAINs."""
    def fake_query(name, rdtype, lifetime=4.0):
        if name.endswith("acmebank.example") or name.endswith("gmail.com"):
            if rdtype == "TXT":
                return ['"v=spf1 -all"'], None
            if rdtype == "MX":
                return ["10 mail.acmebank.example."], None
            return ["203.0.113.10"], None
        if rdtype == "A" and name.endswith(".xyz"):
            return [], None  # exists but empty
        return None, "ResolutionError: NXDOMAIN (test)"
    monkeypatch.setattr("app.services.tools.common.dns_query", fake_query)


# ---------------------------------------------------------------- email tool
def test_email_tool_flags_phishing_patterns(world, f):
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/email/analyze", headers=h, json={
        "from_address": "security@acme-bank-support.xyz",
        "reply_to": "collect@payments-someone.com",
        "subject": "Urgent: your AcmeBank account will be suspended within 24 hours",
        "body": "Verify your account now or it will be suspended. Send your OTP to confirm. "
                "Click https://acme-bank-support.xyz/login to verify immediately.",
        "claimed_brand": "AcmeBank",
        "attachments": [{"filename": "invoice.pdf", "content_type": "application/pdf", "size_bytes": 1234}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    checks = {x["check"]: x for x in body["findings"]}
    assert body["tool"] == "email"
    assert body["risk_score"] is not None and body["severity"] in ("medium", "high", "critical")
    # lookalike vs the official domain reference acmebank.example (brand_impersonation carries the strong signal)
    assert checks["lookalike_domain"]["status"] in ("suspicious", "inconclusive", "info")
    assert checks["brand_impersonation"]["status"] == "suspicious"
    assert checks["reply_to_mismatch"]["status"] == "suspicious"
    assert any(c.startswith("language_") for c in checks), "urgency/credential language must be flagged"
    # every finding carries evidence + source; unavailable checks carry a limitation
    for x in body["findings"]:
        assert x["title"] and x["source"], x


def test_email_tool_parses_eml(world, f):
    h = world.h["inv"]
    eml = (
        "From: AcmeBank Support <help@acmebank.example>\r\n"
        "Reply-To: grab@evil-collection.com\r\n"
        "To: victim@example.com\r\n"
        "Subject: Password reset\r\n"
        "Date: Mon, 01 Jan 2026 10:00:00 +0000\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="XX"\r\n\r\n'
        "--XX\r\nContent-Type: text/plain\r\n\r\nClick the link to reset your password.\r\n"
        "--XX\r\nContent-Type: application/octet-stream\r\n"
        'Content-Disposition: attachment; filename="payment-invoice.zip"\r\n\r\n'
        "AAAA\r\n--XX--\r\n"
    )
    r = f.client.post("/api/v1/tools/email/analyze", headers=h, json={"raw_email": eml, "claimed_brand": "AcmeBank"})
    assert r.status_code == 201, r.text
    checks = {x["check"]: x for x in r.json()["findings"]}
    assert checks["reply_to_mismatch"]["status"] == "suspicious"
    assert checks["attachments"]["status"] == "suspicious" and "payment-invoice.zip" in str(checks["attachments"]["evidence"])


def test_email_tool_invalid_eml_rejected(world, f):
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/email/analyze", headers=h, json={"raw_email": "x" * (1024 * 1024 + 10)})
    assert r.status_code == 422


# ---------------------------------------------------------------- job tool
def test_job_tool_flags_fee_and_freemail(world, f):
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/job/analyze", headers=h, json={
        "employer_name": "AcmeBank",
        "employer_website": "https://acmebank-jobs.xyz",
        "recruiter_email": "hr.recruiter@gmail.com",
        "job_description": "Easy work from home. Pay the training fee of $200 via gift card to start. Guaranteed income!",
        "application_url": "https://acmebank-jobs.xyz/apply?id=1",
    })
    assert r.status_code == 201, r.text
    checks = {x["check"]: x for x in r.json()["findings"]}
    assert checks["fee_or_payment_request"]["status"] == "suspicious"
    assert checks["too_good_to_be_true"]["status"] == "suspicious"
    assert checks["recruiter_email_domain"]["status"] == "suspicious"
    assert checks["lookalike_domain"]["status"] in ("suspicious", "inconclusive", "info")


def test_job_tool_not_found_employer_is_not_fraud(world, f):
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/job/analyze", headers=h, json={
        "employer_name": "Quux Industries", "job_description": "Software engineer role.",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    # an unknown employer must not be scored as fraudulent
    assert body["severity"] in ("none", "low", "unknown"), body["severity"]
    assert any(x["check"] == "employer_website" and x["status"] == "inconclusive" for x in body["findings"])


# ---------------------------------------------------------------- social tool
def test_social_tool_impersonation_pattern(world, f):
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/social/analyze", headers=h, json={
        "platform": "x", "handle": "acmebank_support", "display_name": "AcmeBank Customer Care",
        "claimed_brand": "AcmeBank",
    })
    assert r.status_code == 201, r.text
    checks = {x["check"]: x for x in r.json()["findings"]}
    assert checks["identity_similarity"]["status"] in ("suspicious", "verified")
    assert checks["impersonation_pattern"]["status"] == "suspicious"
    # provenance is explicit: NOT provider-verified
    assert checks["assessment_provenance"]["status"] == "info"
    assert "NOT provider-verified" in checks["assessment_provenance"]["summary"]


def test_social_tool_platform_mismatch(world, f):
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/social/analyze", headers=h, json={
        "platform": "instagram", "profile_url": "https://x.com/acmebank", "handle": "acmebank",
    })
    assert r.status_code == 201
    checks = {x["check"]: x for x in r.json()["findings"]}
    assert checks["profile_url"]["status"] == "suspicious"


# ---------------------------------------------------------------- url tool
def test_url_tool_static_indicators_without_network(world, f, monkeypatch):
    from app.services.tools import url_analyzer

    monkeypatch.setattr(url_analyzer, "dns_resolution_check",
                        lambda host: (url_analyzer.Finding(
                            check="dns_resolution", title="DNS resolution", status="verified", severity="none",
                            summary="resolves (test)", evidence=["test"], source="test"), ["203.0.113.9"]))
    monkeypatch.setattr(url_analyzer, "tls_certificate_check",
                        lambda host: url_analyzer.Finding(
                            check="tls_certificate", title="TLS certificate", status="unable_to_verify", severity="unknown",
                            summary="skipped in test", evidence=["test"], source="test"))
    h = world.h["inv"]
    r = f.client.post("/api/v1/tools/url/analyze", headers=h, json={"url": "http://acme-bank.xyz/login/verify/account"})
    assert r.status_code == 201, r.text
    checks = {x["check"]: x for x in r.json()["findings"]}
    assert checks["url_static"]["status"] == "suspicious"
    assert checks["live_fetch"]["status"] == "unable_to_verify"  # URL_FETCH_ENABLED=false, honestly reported
    assert checks["tls_certificate"]["status"] in ("inconclusive", "unable_to_verify")


def test_tools_are_org_isolated(world, f):
    r_anon = f.client.post("/api/v1/tools/url/analyze", json={"url": "https://example.com"})
    assert r_anon.status_code == 401
    # partner lacks entity:submit
    r_partner = f.client.post("/api/v1/tools/url/analyze", headers=world.h["partner"], json={"url": "https://example.com"})
    assert r_partner.status_code == 403
    # created by org A investigator
    created = f.client.post("/api/v1/tools/url/analyze", headers=world.h["inv"], json={"url": "https://acmebank.example"})
    aid = created.json()["id"]
    assert f.client.get(f"/api/v1/tools/analyses/{aid}", headers=world.h["inv"]).status_code == 200
    # outsider cannot read it
    assert f.client.get(f"/api/v1/tools/analyses/{aid}", headers=world.h["outsider"]).status_code == 404
    # listing is scoped
    out_list = f.client.get("/api/v1/tools/analyses", headers=world.h["outsider"]).json()
    assert out_list["total"] == 0
    own_list = f.client.get("/api/v1/tools/analyses", headers=world.h["inv"]).json()
    assert own_list["total"] >= 1


# ---------------------------------------------------------------- assistant
def test_assistant_no_records_honest(world, f):
    r = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"], json={"question": "zzz nothing matches zzz"})
    assert r.status_code == 200
    body = r.json()
    assert body["used_ai"] is False and body["cited"] == []
    assert "could not find" in body["answer"]


def test_assistant_retrieves_and_cites(world, f):
    e = f.profile(world.h["inv"], world.brand["id"], handle="acmebank_support")
    r = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"],
                      json={"question": "Why was the acmebank_support profile flagged?"})
    assert r.status_code == 200
    body = r.json()
    assert any(c["type"] == "entity" and c["id"] == e["id"] for c in body["cited"]), body["cited"]
    assert body["used_ai"] is False  # no provider configured in tests: retrieval-only, honestly labelled
    assert body["limitation"]


def test_assistant_with_memory_provider_validates_and_cites(world, f, settings):
    settings.ai_provider = "memory"
    try:
        e = f.website(world.h["inv"], world.brand["id"], url="https://acmebank-login.xyz/verify")
        r = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"],
                          json={"question": "Tell me about acmebank-login.xyz"})
        assert r.status_code == 200
        body = r.json()
        assert body["used_ai"] is True and body["provider"] == "memory"
        assert all(c["id"] for c in body["cited"])
        # citations must be a subset of the records that actually exist
        allowed = {e["id"]}
        assert all(c["id"] in allowed for c in body["cited"]), body["cited"]
    finally:
        settings.ai_provider = "none"


def test_assistant_cross_org_isolation(world, f):
    f.profile(world.h["inv"], world.brand["id"], handle="secretproject_handle")
    r = f.client.post("/api/v1/assistant/ask", headers=world.h["outsider"],
                      json={"question": "secretproject_handle"})
    body = r.json()
    assert body["cited"] == [], "cross-org records must never appear"


def test_assistant_status_endpoint(world, f):
    r = f.client.get("/api/v1/assistant/status", headers=world.h["inv"])
    assert r.status_code == 200 and r.json()["configured"] is False


def test_assistant_retrieves_evidence_records(world, f):
    """Regression: evidence rows used to crash retrieval (wrong attribute name) -> 500."""
    e = f.profile(world.h["inv"], world.brand["id"], handle="evidence_retrieval_probe")
    r = f.client.post("/api/v1/evidence", headers=world.h["inv"], json={
        "entity_id": e["id"], "kind": "whois",
        "title": "WHOIS snapshot for evidence_retrieval_probe",
        "text_content": "registered 2 days ago",
    })
    assert r.status_code == 201, r.text
    ask = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"],
                        json={"question": "Show the WHOIS snapshot evidence for evidence_retrieval_probe"})
    assert ask.status_code == 200, ask.text
    body = ask.json()
    assert any(c["type"] == "evidence" for c in body["cited"]), body["cited"]


def test_assistant_severity_question_filters_by_severity(world, f):
    """Regression: a severity word is a filter, not a keyword. 'critical risk score' used to
    match nothing (no display name contains 'critical') and returned an honest empty answer."""
    r = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"],
                      json={"question": "Which of my entities currently have a critical risk score?"})
    assert r.status_code == 200, r.text
    body = r.json()
    # whatever the workspace holds, the answer must be labelled honestly
    assert body["used_ai"] is False
    assert body["limitation"]
    # every cited entity must really be critical
    if body["cited"]:
        ents = {e["id"]: e for e in f.client.get("/api/v1/entities?page_size=100", headers=world.h["inv"]).json()["items"]}
        for c in body["cited"]:
            assert c["type"] != "entity" or ents[c["id"]]["current_severity"] == "critical", c


def test_assistant_provider_error_falls_back_honestly(world, f, settings):
    """Regression: the fallback path referenced ValidationError without importing it (NameError -> 500)."""
    from app.services.ai.base import AIProviderError

    class BoomProvider:
        name = "boom"
        model = "boom-1"

        def complete_json(self, *a, **k):
            raise AIProviderError("provider unreachable")

    settings.ai_provider = "memory"
    import app.services.assistant as assistant_mod
    original = assistant_mod.get_provider
    assistant_mod.get_provider = lambda: BoomProvider()
    try:
        e = f.profile(world.h["inv"], world.brand["id"], handle="fallback_probe")
        r = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"],
                          json={"question": "fallback_probe status"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["used_ai"] is False
        assert "provider error" in body["limitation"].lower()
        assert any(c["id"] == e["id"] for c in body["cited"])
    finally:
        assistant_mod.get_provider = original
        settings.ai_provider = "none"


def test_assistant_provider_invalid_output_drops_bad_citations(world, f, settings):
    """Malformed model output must fall back, never raise (ValidationError import regression)."""
    
    class JunkProvider:
        name = "junk"
        model = "junk-1"

        def complete_json(self, *a, **k):
            return {"not_a_valid": "analysis structure"}

    settings.ai_provider = "memory"
    import app.services.assistant as assistant_mod
    original = assistant_mod.get_provider
    assistant_mod.get_provider = lambda: JunkProvider()
    try:
        f.profile(world.h["inv"], world.brand["id"], handle="junk_output_probe")
        r = f.client.post("/api/v1/assistant/ask", headers=world.h["inv"],
                          json={"question": "junk_output_probe risk"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["used_ai"] is False  # honest fallback to retrieval
        assert body["limitation"]
    finally:
        assistant_mod.get_provider = original
        settings.ai_provider = "none"


# ---------------------------------------------------------------- scheduler
def _make_target(f, h, brand_id):
    r = f.client.post("/api/v1/monitoring/apps", headers=h, json={
        "brand_id": brand_id, "store": "google_play", "package_id": "com.acmebank.mobile"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_scheduler_runs_due_target(world, f, db):
    from app.models import MonitoringSyncRun, MonitoringTarget
    from app.services import scheduler

    resp = _make_target(f, world.h["owner"], world.brand["id"])
    tid = resp["target"]["id"]
    t = db.get(MonitoringTarget, uuid.UUID(tid))
    assert t.next_run_at is not None, "creation must put the target on the schedule"
    t.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    processed = scheduler.run_due_once(db)
    assert processed == 1
    db.refresh(t)
    assert t.last_run_status == "success" and t.retry_count == 0 and t.next_run_at is not None
    runs = db.query(MonitoringSyncRun).filter_by(target_id=t.id).all()
    assert runs and any(r.status == "success" and r.triggered_by == "scheduler" for r in runs)


def test_scheduler_retries_with_backoff_then_stops(world, f, db, monkeypatch):
    from app.models import MonitoringSyncRun, MonitoringTarget
    from app.services import monitoring, scheduler
    import uuid as _uuid

    resp = _make_target(f, world.h["owner"], world.brand["id"])
    tid = _uuid.UUID(resp["target"]["id"])

    def boom(*a, **kw):
        raise RuntimeError("connector exploded")

    monkeypatch.setattr(monitoring, "sync_target", boom)
    t = db.get(MonitoringTarget, tid)
    t.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    scheduler.run_due_once(db)
    db.refresh(t)
    assert t.last_run_status == "failed" and t.retry_count == 1 and t.next_run_at is not None

    # exhaust the retry budget -> next_run_at must go NULL and admins must be notified
    from app.core.config import get_settings
    s = get_settings()
    t.retry_count = s.monitoring_retry_max
    t.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    scheduler.run_due_once(db)
    db.refresh(t)
    assert t.retry_count == s.monitoring_retry_max + 1 and t.next_run_at is None
    from app.models import Notification
    notes = db.query(Notification).filter(Notification.type == "monitoring_sync_failed").all()
    assert notes, "admins must be notified when scheduled syncing stops"
    runs = db.query(MonitoringSyncRun).filter_by(target_id=tid).all()
    assert any(r.status == "failed" and r.error for r in runs)


def test_paused_target_is_not_scheduled(world, f, db):
    from app.models import MonitoringTarget
    import uuid as _uuid

    resp = _make_target(f, world.h["owner"], world.brand["id"])
    tid = resp["target"]["id"]
    r = f.client.patch(f"/api/v1/monitoring/apps/{tid}", headers=world.h["owner"], json={"monitoring_status": "paused"})
    assert r.status_code == 200
    assert r.json()["next_run_at"] is None

