"""Integrations API: catalog, connect validation, encryption, test, sync, disconnect."""
from __future__ import annotations

from app.services.crypto_utils import fernet as make_fernet

CATALOG_KEYS = ("x_twitter", "instagram", "google_play", "app_store", "web_scraping", "dns_whois", "url_scan")

# Every required secret for x_twitter (all >= 8 chars, per validate_config).
X_TWITTER_CONFIG = {
    "bearer_token": "AAAA-demo-bearer-token-123456",
    "api_key": "demo-api-key-123456",
    "api_secret": "demo-api-secret-123456",
}


def test_catalog_lists_all_providers(client, world):
    h = world.h["admin"]
    r = client.get("/api/v1/integrations", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["items"]) == len(CATALOG_KEYS)
    by_key = {i["key"]: i for i in body["items"]}
    for key in CATALOG_KEYS:
        assert key in by_key, f"missing provider {key}"
        item = by_key[key]
        assert item["status"] == "not_configured"
        assert item["config_preview"] == {}
        assert item["connected_by"] is None
        assert isinstance(item["config_fields"], list)
        assert item["requires_credentials"] in (True, False)

    play = by_key["google_play"]
    play_fields = {field["key"]: field for field in play["config_fields"]}
    assert {"service_account_email", "private_key"} <= play_fields.keys()
    assert play_fields["private_key"]["type"] == "secret"
    assert "not a public catalog search API" in play["description"]
    assert "do not search the public App Store catalog" in by_key["app_store"]["description"]

    # Detail of one provider when not configured.
    r = client.get("/api/v1/integrations/x_twitter", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "not_configured"


def test_unknown_provider_is_404(client, world):
    r = client.get("/api/v1/integrations/nope", headers=world.h["admin"])
    assert r.status_code == 404


def test_connect_masks_secrets_and_encrypts_at_rest(client, world):
    h = world.h["admin"]
    r = client.post(
        "/api/v1/integrations/x_twitter/connect",
        headers=h,
        json={"config": X_TWITTER_CONFIG},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "configured"
    # Secrets are masked in the preview, never echoed.
    assert body["config_preview"]["bearer_token"] == "••••"
    assert body["config_preview"]["api_key"] == "••••"
    raw = r.text
    for secret in X_TWITTER_CONFIG.values():
        assert secret not in raw, "plaintext secret leaked in the response"
    assert body["connected_by"]["email"] == world.users["admin"].email

    # The stored blob never contains plaintext either.
    from app.db.session import get_sessionmaker
    from app.models.integration import IntegrationConfig

    db = get_sessionmaker()()
    try:
        row = db.query(IntegrationConfig).filter_by(provider_key="x_twitter").one()
        assert row.status == "configured"
        for secret in X_TWITTER_CONFIG.values():
            assert secret not in (row.config_encrypted or "")
    finally:
        db.close()


def test_connect_stored_blob_is_fernet_encrypted(client, world):
    h = world.h["admin"]
    client.post("/api/v1/integrations/x_twitter/connect", headers=h, json={"config": X_TWITTER_CONFIG})

    from app.db.session import get_sessionmaker
    from app.models.integration import IntegrationConfig

    db = get_sessionmaker()()
    try:
        row = db.query(IntegrationConfig).filter_by(provider_key="x_twitter").one()
        token = row.config_encrypted
        assert token.startswith("gAAAAA"), "expected a Fernet token"
        # Decrypting with the app-derived key recovers the original config.
        assert make_fernet().decrypt(token.encode()).decode().count("demo-api-key") == 1
    finally:
        db.close()


def test_connect_requires_required_fields(client, world):
    r = client.post(
        "/api/v1/integrations/x_twitter/connect",
        headers=world.h["admin"],
        json={"config": {"api_key": "only-one-field-123"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_connect_rejects_unknown_field_and_short_secret(client, world):
    h = world.h["admin"]
    r = client.post(
        "/api/v1/integrations/x_twitter/connect",
        headers=h,
        json={"config": {**X_TWITTER_CONFIG, "bogus_field": "x"}},
    )
    assert r.status_code == 422

    r = client.post(
        "/api/v1/integrations/x_twitter/connect",
        headers=h,
        json={"config": {**X_TWITTER_CONFIG, "api_key": "short"}},
    )
    assert r.status_code == 422


def test_every_integration_route_is_admin_only(client, world):
    """org:manage (admin) for every route — reads included — because these store org-wide credentials."""
    # A brand owner lacks org:manage.
    r = client.post(
        "/api/v1/integrations/x_twitter/connect",
        headers=world.h["owner"],
        json={"config": X_TWITTER_CONFIG},
    )
    assert r.status_code == 403

    # Investigator (has connector:run, but NOT org:manage) is rejected everywhere: 6 endpoints.
    inv = world.h["inv"]
    for method, path in (
        ("GET", "/api/v1/integrations"),
        ("GET", "/api/v1/integrations/x_twitter"),
        ("POST", "/api/v1/integrations/x_twitter/connect"),
        ("POST", "/api/v1/integrations/x_twitter/disconnect"),
        ("POST", "/api/v1/integrations/x_twitter/test"),
        ("POST", "/api/v1/integrations/x_twitter/sync"),
    ):
        r = client.request(method, path, headers=inv, json={} if method == "POST" else None)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}: {r.text}"

    # partner equally locked out; no token at all stays 401
    assert client.get("/api/v1/integrations", headers=world.h["partner"]).status_code == 403
    assert client.get("/api/v1/integrations").status_code == 401


def test_list_requires_auth(client):
    assert client.get("/api/v1/integrations").status_code == 401


def test_disconnect_returns_to_not_configured(client, world):
    h = world.h["admin"]
    client.post("/api/v1/integrations/x_twitter/connect", headers=h, json={"config": X_TWITTER_CONFIG})

    r = client.post("/api/v1/integrations/x_twitter/disconnect", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "not_configured"
    assert r.json()["config_preview"] == {}

    r = client.get("/api/v1/integrations/x_twitter", headers=h)
    assert r.json()["status"] == "not_configured"

    # Reconnect works after a disconnect.
    r = client.post("/api/v1/integrations/x_twitter/connect", headers=h, json={"config": X_TWITTER_CONFIG})
    assert r.status_code == 200
    assert r.json()["status"] == "configured"

    # Disconnect is idempotent (no 404 when nothing is stored).
    client.post("/api/v1/integrations/x_twitter/disconnect", headers=h)
    r = client.post("/api/v1/integrations/x_twitter/disconnect", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "not_configured"


def test_sync_with_connector_reports_synthetic_data(client, world):
    h = world.h["admin"]
    client.post("/api/v1/integrations/x_twitter/connect", headers=h, json={"config": X_TWITTER_CONFIG})
    r = client.post("/api/v1/integrations/x_twitter/sync", headers=h, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["synced"] >= 0
    assert body["created_entities"] >= 0
    # The message must be explicit that the data is synthetic, not live.
    msg = body["message"].lower()
    assert "synthetic" in msg
    assert "not live" in msg or "not fetched" in msg


def test_sync_without_connector_is_400(client, world):
    h = world.h["admin"]
    client.post("/api/v1/integrations/dns_whois/connect", headers=h, json={"config": {}})
    r = client.post("/api/v1/integrations/dns_whois/sync", headers=h, json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "no_connector_available"


def test_sync_when_not_configured_is_400(client, world):
    r = client.post(
        "/api/v1/integrations/instagram/sync",
        headers=world.h["admin"],
        json={},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "not_configured"


def test_test_endpoint_never_fakes_connection(client, world):
    h = world.h["admin"]
    # Not configured -> explicit error, not a fake success.
    r = client.post("/api/v1/integrations/x_twitter/test", headers=h)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "not_configured"

    # Configured: the credential provider must NOT claim a verified connection.
    client.post("/api/v1/integrations/x_twitter/connect", headers=h, json={"config": X_TWITTER_CONFIG})
    r = client.post("/api/v1/integrations/x_twitter/test", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False, "a credential provider without live access must not report ok"
    assert "verif" in body["message"].lower() or "could not" in body["message"].lower()
    # No secret appears in the message.
    for secret in X_TWITTER_CONFIG.values():
        assert secret not in body["message"]


def test_dns_whois_test_does_a_real_lookup(client, world):
    h = world.h["admin"]
    client.post("/api/v1/integrations/dns_whois/connect", headers=h, json={"config": {"check_domain": "example.com"}})
    r = client.post("/api/v1/integrations/dns_whois/test", headers=h)
    assert r.status_code == 200
    body = r.json()
    # Whether it resolves or not, the message must describe a real DNS attempt.
    assert "dns" in body["message"].lower()
