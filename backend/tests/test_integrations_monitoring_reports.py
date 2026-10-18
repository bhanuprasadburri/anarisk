"""Integrations, monitoring and reports APIs (tasks 4-6) + a small notifications smoke test."""
from __future__ import annotations

from datetime import date, timedelta

from app.models import Notification
from app.models.enums import UserRole
from app.services.reports import CSV_COLUMNS

SECRET_VALUE = "SuperSecret-DoNotEcho-1234567890"


# ---------------------------------------------------------------- integrations
def test_catalog_honest_and_org_scoped(client, world):
    r = client.get("/api/v1/integrations", headers=world.h["inv"])
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {i["key"] for i in body["items"]}
    assert keys == {"x_twitter", "instagram", "google_play", "app_store", "web_scraping", "dns_whois", "url_scan"}
    assert body["total"] == 7
    assert all(i["status"] == "not_configured" for i in body["items"])
    item = next(i for i in body["items"] if i["key"] == "dns_whois")
    assert item["category"] == "infrastructure" and item["requires_credentials"] is False
    assert item["config_preview"] == {} and item["connected_by"] is None

    # a configuration stored by ANOTHER organization is invisible here (org scoping)
    assert client.post("/api/v1/integrations/dns_whois/connect", headers=world.h["outsider"],
                       json={"config": {"check_domain": "example.org"}}).status_code == 200
    r = client.get("/api/v1/integrations", headers=world.h["inv"])
    assert next(i for i in r.json()["items"] if i["key"] == "dns_whois")["status"] == "not_configured"


def test_connect_validation_errors(client, world):
    post = lambda key, cfg: client.post(f"/api/v1/integrations/{key}/connect", headers=world.h["inv"], json={"config": cfg})
    r = post("x_twitter", {})  # missing required secrets
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"bearer_token", "api_key", "api_secret"} <= fields

    r = post("x_twitter", {"bearer_token": "short", "api_key": "long-enough-key", "api_secret": "long-enough-secret"})
    assert r.status_code == 422
    assert any(d["field"] == "bearer_token" and "at least 8" in d["message"] for d in r.json()["error"]["details"])

    r = post("web_scraping", {"target_url": "https://example.com/x", "method": "POST"})  # not in options
    assert r.status_code == 422
    assert any(d["field"] == "method" for d in r.json()["error"]["details"])

    r = post("web_scraping", {"target_url": "ftp://not-http"})
    assert r.status_code == 422
    assert any(d["field"] == "target_url" for d in r.json()["error"]["details"])


def test_test_endpoint_requires_configuration(client, world):
    r = client.post("/api/v1/integrations/dns_whois/test", headers=world.h["inv"])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "not_configured"


def test_dns_whois_connect_and_real_dns_test(client, world):
    r = client.post("/api/v1/integrations/dns_whois/connect", headers=world.h["inv"],
                    json={"config": {"check_domain": "example.com"}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "configured"
    assert r.json()["connected_by"]["email"] == world.users["inv"].email

    r = client.post("/api/v1/integrations/dns_whois/test", headers=world.h["inv"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["ok"], bool)  # offline CI may fail the lookup: either outcome is honest
    assert body["message"] and len(body["message"]) > 10
    assert body["checked_at"]

    # disconnect back to not_configured, and testing it again fails
    r = client.post("/api/v1/integrations/dns_whois/disconnect", headers=world.h["inv"])
    assert r.status_code == 200 and r.json()["status"] == "not_configured"
    assert client.post("/api/v1/integrations/dns_whois/test", headers=world.h["inv"]).status_code == 400


def test_secrets_never_echoed_after_connect(client, world):
    cfg = {"bearer_token": SECRET_VALUE, "api_key": "another-secret-key-9876", "api_secret": "third-secret-key-5432"}
    r = client.post("/api/v1/integrations/x_twitter/connect", headers=world.h["inv"], json={"config": cfg})
    assert r.status_code == 200, r.text
    assert SECRET_VALUE not in r.text

    r = client.get("/api/v1/integrations", headers=world.h["inv"])
    assert r.status_code == 200 and SECRET_VALUE not in r.text
    item = next(i for i in r.json()["items"] if i["key"] == "x_twitter")
    assert item["status"] == "configured"
    assert item["config_preview"]["bearer_token"] == "••••"
    assert item["config_preview"]["api_key"] == "••••"
    assert item["connected_by"]["email"] == world.users["inv"].email

    r = client.get("/api/v1/integrations/x_twitter", headers=world.h["inv"])
    assert r.status_code == 200 and SECRET_VALUE not in r.text


def test_credential_provider_test_is_honest_not_fake(client, world):
    client.post("/api/v1/integrations/x_twitter/connect", headers=world.h["inv"], json={"config": {
        "bearer_token": SECRET_VALUE, "api_key": "another-secret-key-9876", "api_secret": "third-secret-key-5432"}})
    r = client.post("/api/v1/integrations/x_twitter/test", headers=world.h["inv"])
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False  # NEVER fake success for credentials stored but unverifiable
    assert "could not be verified" in body["message"] or "unverified" in body["message"].lower()


def test_sync_runs_sample_connector_or_rejects(client, world):
    # configured provider WITH a sample connector -> honest synthetic sync
    client.post("/api/v1/integrations/x_twitter/connect", headers=world.h["inv"], json={"config": {
        "bearer_token": SECRET_VALUE, "api_key": "another-secret-key-9876", "api_secret": "third-secret-key-5432"}})
    r = client.post("/api/v1/integrations/x_twitter/sync", headers=world.h["inv"], json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["synced"] >= 1 and body["created_entities"] >= 1
    assert "synthetic" in body["message"].lower()

    # configured provider WITHOUT a connector -> 400 no_connector_available
    assert client.post("/api/v1/integrations/web_scraping/connect", headers=world.h["inv"],
                       json={"config": {"target_url": "https://example.com/page"}}).status_code == 200
    r = client.post("/api/v1/integrations/web_scraping/sync", headers=world.h["inv"], json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "no_connector_available"


# ----------------------------------------------------------------- monitoring
def _monitoring_body(world, **over):
    body = {"brand_id": str(world.brand["id"]), "package_id": "com.acme.coolapp", "store": "google_play",
            "store_url": "https://play.google.com/store/apps/details?id=com.acme.coolapp"}
    body.update(over)
    return body


def test_monitoring_create_list_patch_delete(client, world):
    h = world.h["inv"]
    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(world))
    assert r.status_code == 201, r.text
    target = r.json()["target"]
    assert target["package_id"] == "com.acme.coolapp" and target["monitoring_status"] == "active"
    assert target["brand"]["id"] == str(world.brand["id"])
    assert target["entity"] is not None and target["entity"]["provenance"] == "synthetic"

    r = client.get("/api/v1/monitoring/apps", headers=h)
    assert r.status_code == 200
    page = r.json()
    assert page["total"] >= 1 and any(i["id"] == target["id"] for i in page["items"])

    # duplicate (brand, package) -> 409
    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(world))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "duplicate_monitoring_target"

    # patch status, then delete
    r = client.patch(f"/api/v1/monitoring/apps/{target['id']}", headers=h, json={"monitoring_status": "paused"})
    assert r.status_code == 200 and r.json()["monitoring_status"] == "paused"

    r = client.delete(f"/api/v1/monitoring/apps/{target['id']}", headers=h)
    assert r.status_code == 204
    r = client.get("/api/v1/monitoring/apps", headers=h)
    assert all(i["id"] != target["id"] for i in r.json()["items"])

    # outsider (other organization) cannot see or delete it
    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(world))
    tid = r.json()["target"]["id"]
    assert client.delete(f"/api/v1/monitoring/apps/{tid}", headers=world.h["outsider"]).status_code == 404


def test_monitoring_validation_and_duplicates(client, world):
    h = world.h["inv"]
    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(world, package_id="nodots"))
    assert r.status_code == 422
    assert any(d["field"] == "package_id" for d in r.json()["error"]["details"])

    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(
        world, store_url="https://evil.example/store/apps/details?id=com.acme.coolapp"))
    assert r.status_code == 422
    assert any(d["field"] == "store_url" for d in r.json()["error"]["details"])

    # wrong package in a well-formed Play URL is also rejected
    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(
        world, store_url="https://play.google.com/store/apps/details?id=com.other.app"))
    assert r.status_code == 422

    # app_store accepts numeric ids / slugs
    r = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(
        world, package_id="1234567890", store="app_store",
        store_url="https://apps.apple.com/us/app/some-app/id1234567890"))
    assert r.status_code == 201, r.text


def test_monitoring_sync_updates_entity_and_says_synthetic(client, world):
    h = world.h["inv"]
    target = client.post("/api/v1/monitoring/apps", headers=h, json=_monitoring_body(world)).json()["target"]
    r = client.post(f"/api/v1/monitoring/apps/{target['id']}/sync", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity"] is not None and body["entity"]["id"] == target["entity"]["id"]
    assert "synthetic" in body["message"].lower()
    assert body["target"]["last_sync_at"] is not None
    assert body["target"]["publisher_name"]  # attributes were refreshed by the sample connector
    assert body["entity"]["current_risk_score"] is not None  # analysis ran


# -------------------------------------------------------------------- reports
OVERVIEW_KEYS = {
    "generated_at", "date_range", "totals", "threat_distribution", "cases_by_status", "risk_trend",
    "threats_by_channel", "top_connected_entities", "entity_type_distribution", "severity_by_type",
    "mobile_apps", "evidence", "data_notes",
}


def test_reports_overview_shape_and_full_trend_window(client, world):
    h = world.h["inv"]
    today = date.today()
    frm = (today - timedelta(days=6)).isoformat()
    r = client.get("/api/v1/reports/overview", headers=h, params={"from": frm, "to": today.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert OVERVIEW_KEYS <= set(body)
    assert body["date_range"] == {"from": frm, "to": today.isoformat()}

    # every day in the window is present exactly once, with explicit null/0 fill
    days = [d["date"] for d in body["risk_trend"]]
    assert days == [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]
    assert all(set(d) == {"date", "avg_risk", "detections"} for d in body["risk_trend"])
    assert all(isinstance(d["detections"], int) for d in body["risk_trend"])

    assert all(isinstance(v, int) for v in body["totals"].values())
    assert set(body["threat_distribution"]) == {"critical", "high", "medium", "low", "unknown"}
    assert set(body["cases_by_status"]) == {"detected", "triaged", "under_review", "assigned", "escalated", "resolved"}
    assert [c["channel"] for c in body["threats_by_channel"]] == ["Social", "Web", "App", "Image", "Other"]
    assert any("explainable rule-based heuristic" in n for n in body["data_notes"])
    assert any("synthetic demo data" in n for n in body["data_notes"])


def test_reports_csv_exports_and_permissions(client, world):
    h = world.h["inv"]
    today = date.today().isoformat()
    for report in ("threats", "cases", "entities", "apps", "evidence"):
        r = client.get("/api/v1/reports/export/csv", headers=h, params={"report": report})
        assert r.status_code == 200, f"{report}: {r.text[:200]}"
        assert "text/csv" in r.headers["content-type"]
        assert r.headers["content-disposition"] == f'attachment; filename="anarisk-{report}-{today}.csv"'
        lines = r.text.splitlines()
        assert lines and lines[0].split(",") == CSV_COLUMNS[report]  # proper header row

    r = client.get("/api/v1/reports/export/csv", headers=h, params={"report": "nonsense"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"

    # partner role has no dashboard:read -> overview forbidden
    r = client.get("/api/v1/reports/overview", headers=world.h["partner"])
    assert r.status_code == 403


def test_reports_empty_database_returns_zeros(client, f, world):
    empty_user = f.user(UserRole.BRAND_OWNER)
    h = f.headers(empty_user)
    frm = (date.today() - timedelta(days=6)).isoformat()
    r = client.get("/api/v1/reports/overview", headers=h, params={"from": frm})
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(v == 0 for v in body["totals"].values())
    assert all(v == 0 for v in body["threat_distribution"].values())
    assert all(v == 0 for v in body["cases_by_status"].values())
    assert len(body["risk_trend"]) == 7
    assert all(c["count"] == 0 for c in body["threats_by_channel"])
    assert body["top_connected_entities"] == []

    r = client.get("/api/v1/reports/export/csv", headers=h, params={"report": "entities"})
    assert r.status_code == 200
    assert len(r.text.splitlines()) == 1  # header only


# ------------------------------------------------- notifications (task 3 API)
def test_notifications_list_and_mark_read(client, world, db):
    h = world.h["inv"]
    db.add(Notification(user_id=world.users["inv"].id, type="case_created",
                        title="New case NN-2026-000001", body="needs triage", link_url="/cases/x"))
    db.commit()
    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200, r.text
    page = r.json()
    assert {"items", "total", "unread_count", "page", "page_size", "pages"} <= set(page)
    assert page["unread_count"] >= 1
    assert page["items"][0]["created_at"] and page["items"][0]["is_read"] is False

    nid = page["items"][0]["id"]
    r = client.post("/api/v1/notifications/read", headers=h, json={"ids": [nid]})
    assert r.status_code == 200
    assert r.json()["updated"] == 1 and r.json()["unread_count"] == page["unread_count"] - 1

    # users only ever see their own notifications
    r = client.get("/api/v1/notifications", headers=world.h["outsider"])
    assert r.status_code == 200 and r.json()["unread_count"] == 0
