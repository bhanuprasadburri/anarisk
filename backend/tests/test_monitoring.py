"""Monitoring API: list/create/patch/delete targets, sync, validation, permissions."""
from __future__ import annotations


def test_list_monitoring_empty(client, world):
    r = client.get("/api/v1/monitoring/apps", headers=world.h["inv"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert body["total"] == 0


def test_create_list_patch_delete_target(client, world):
    admin = world.h["admin"]
    brand_id = world.brand["id"]

    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={
            "brand_id": brand_id,
            "package_id": "com.nimbus.example.watch",
            "store": "google_play",
            "store_url": "https://play.google.com/store/apps/details?id=com.nimbus.example.watch",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    target = body["target"]
    assert target["package_id"] == "com.nimbus.example.watch"
    assert target["store"] == "google_play"
    assert target["monitoring_status"] == "active"
    assert target["brand"]["id"] == brand_id
    assert "synthetic" in body["message"].lower()

    r = client.get("/api/v1/monitoring/apps", headers=admin)
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == target["id"]

    r = client.get(f"/api/v1/monitoring/apps/{target['id']}", headers=admin)
    assert r.status_code == 405  # no detail route; the list is the read model

    # Pause monitoring.
    r = client.patch(
        f"/api/v1/monitoring/apps/{target['id']}",
        headers=admin,
        json={"monitoring_status": "paused"},
    )
    assert r.status_code == 200
    assert r.json()["monitoring_status"] == "paused"

    # Filter by monitoring_status.
    r = client.get("/api/v1/monitoring/apps?monitoring_status=active", headers=admin)
    assert r.json()["total"] == 0
    r = client.get("/api/v1/monitoring/apps?monitoring_status=paused", headers=admin)
    assert r.json()["total"] == 1

    # Search by package id.
    r = client.get("/api/v1/monitoring/apps?q=watch", headers=admin)
    assert r.json()["total"] == 1

    # Sync the target: honest synthetic message + linked entity.
    r = client.post(f"/api/v1/monitoring/apps/{target['id']}/sync", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"]["id"] == target["id"]
    assert body["entity"] is not None
    assert "synthetic" in body["message"].lower()

    # Delete.
    r = client.delete(f"/api/v1/monitoring/apps/{target['id']}", headers=admin)
    assert r.status_code == 204
    r = client.get("/api/v1/monitoring/apps", headers=admin)
    assert r.json()["total"] == 0


def test_store_filter_is_server_side(client, world):
    """GET /monitoring/apps?store=... filters in SQL: one store's rows never leak into another's page."""
    admin = world.h["admin"]
    brand_id = world.brand["id"]

    def _create(pkg: str, store: str, url: str | None = None) -> dict:
        r = client.post(
            "/api/v1/monitoring/apps",
            headers=admin,
            json={"brand_id": brand_id, "package_id": pkg, "store": store, "store_url": url},
        )
        assert r.status_code == 201, r.text
        return r.json()["target"]

    gp = _create("com.example.playapp", "google_play",
                 "https://play.google.com/store/apps/details?id=com.example.playapp")
    ios = _create("1234567890", "app_store")

    r = client.get("/api/v1/monitoring/apps?store=app_store", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == ios["id"]
    assert all(i["store"] == "app_store" for i in body["items"])

    r = client.get("/api/v1/monitoring/apps?store=google_play", headers=admin)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == gp["id"]

    # No store param → everything (the filter is opt-in, not a default narrowing).
    assert client.get("/api/v1/monitoring/apps", headers=admin).json()["total"] == 2

    # An unknown store value is rejected (422) instead of silently returning an unfiltered list.
    assert client.get("/api/v1/monitoring/apps?store=steam", headers=admin).status_code == 422


def test_create_rejects_bad_input(client, world):
    admin = world.h["admin"]
    brand_id = world.brand["id"]

    # Not a reverse-DNS package id.
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={"brand_id": brand_id, "package_id": "not a package!", "store": "google_play"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"

    # Store URL that does not match the package.
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={
            "brand_id": brand_id,
            "package_id": "com.nimbus.mismatch",
            "store": "google_play",
            "store_url": "https://evil.example.com/app",
        },
    )
    assert r.status_code == 422

    # Unknown brand.
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={"brand_id": "00000000-0000-0000-0000-000000000000", "package_id": "com.nimbus.ghost"},
    )
    assert r.status_code == 404

    # Duplicate package for the same brand.
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={"brand_id": brand_id, "package_id": "com.nimbus.dup.app"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={"brand_id": brand_id, "package_id": "com.nimbus.dup.app"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "duplicate_monitoring_target"


def test_monitoring_permissions(client, world):
    brand_id = world.brand["id"]

    # An investigator can read and create.
    r = client.get("/api/v1/monitoring/apps", headers=world.h["inv"])
    assert r.status_code == 200
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=world.h["inv"],
        json={"brand_id": brand_id, "package_id": "com.nimbus.inv.created"},
    )
    assert r.status_code == 201, r.text

    # A partner cannot create (no entity:submit) but can read.
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=world.h["partner"],
        json={"brand_id": brand_id, "package_id": "com.nimbus.partner.blocked"},
    )
    assert r.status_code == 403
    r = client.get("/api/v1/monitoring/apps", headers=world.h["partner"])
    assert r.status_code == 200

    # A member of another org sees no rows (brand scoping), not an error.
    r = client.get("/api/v1/monitoring/apps", headers=world.h["outsider"])
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # Unauthenticated.
    assert client.get("/api/v1/monitoring/apps").status_code == 401


def test_sync_requires_connector_run(client, world):
    admin = world.h["admin"]
    r = client.post(
        "/api/v1/monitoring/apps",
        headers=admin,
        json={"brand_id": world.brand["id"], "package_id": "com.nimbus.syncperm"},
    )
    target = r.json()["target"]

    # A brand owner cannot sync (no connector:run).
    r = client.post(f"/api/v1/monitoring/apps/{target['id']}/sync", headers=world.h["owner"])
    assert r.status_code == 403


def test_sync_unknown_target_404(client, world):
    r = client.post(
        "/api/v1/monitoring/apps/00000000-0000-0000-0000-000000000000/sync",
        headers=world.h["admin"],
    )
    assert r.status_code == 404
