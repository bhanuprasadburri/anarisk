import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.models import Base
from tests.conftest import _TEST_URL, _db_is_available, alembic_cfg, png_bytes

BIO = "AcmeBank - secure everyday banking for everyone. Customer care is available 24/7 - DM us!"


@pytest.fixture
def populated(client, f, world):
    h, bid = world.h["inv"], world.brand["id"]
    ents = {
        "p": f.profile(h, bid, handle="acmebank_support_help", bio=BIO, links=["https://acmebank-bonus.top/claim"], account_created_at="2026-10-08T00:00:00Z"),
        "w": f.website(h, bid, url="https://acmebank-bonus.top/claim"),
        "b": f.profile(h, bid, handle="gardening_fan", bio="I post about roses and tomatoes every single week of the year.", account_created_at="2015-01-01T00:00:00Z"),
        "a": f.entity(h, bid, "mobile_app", provenance="synthetic", attributes={
            "app_name": "AcmeBank Rewards Official", "package_id": "com.acmebank.rewards", "store": "google_play", "publisher_name": "Acme Bank Digital Ltd",
            "description": "Verify at https://acmebank-bonus.top/claim", "permissions": ["READ_SMS", "INTERNET", "SYSTEM_ALERT_WINDOW"], "permissions_source": "manual",
            "linked_websites": ["https://acmebank-bonus.top/claim"]}),
        "u": f.entity(h, bid, "domain", attributes={"domain": "never-analyzed.org"}),
    }
    client.post("/api/v1/graph/discover", params={"brand_id": bid}, headers=h)
    for k in ("p", "w", "b", "a"):
        client.post(f"/api/v1/entities/{ents[k]['id']}/analyze", headers=h)
    class P: pass
    p = P(); p.ents, p.h, p.bid, p.w = ents, h, bid, world
    return p


def test_dashboard_stats_are_database_backed(client, populated):
    p = populated
    s = client.get("/api/v1/dashboard/stats", headers=p.h).json()
    ents = client.get("/api/v1/entities", params={"page_size": 100}, headers=p.h).json()["items"]
    t = s["totals"]
    assert t["monitored_entities"] == 5 == len(ents)
    assert t["unassessed_entities"] == 1 == sum(1 for e in ents if e["current_severity"] == "unknown")
    assert t["high_risk_entities"] == sum(1 for e in ents if e["current_severity"] in ("high", "critical")) >= 2
    assert sum(s["risk_distribution"].values()) == 5 and s["risk_distribution"]["low"] >= 1
    assert s["entity_type_distribution"] == {"social_profile": 2, "website": 1, "domain": 1, "image": 0, "mobile_app": 1}
    assert s["data_provenance"] == {"collected": 0, "manual": 4, "synthetic": 1}
    assert len(s["recent_detections"]) == 4 and s["recent_detections"][0]["last_assessed_at"] >= s["recent_detections"][-1]["last_assessed_at"]
    risks = [e["risk_score"] for e in s["top_risk_entities"]]
    assert risks == sorted(risks, reverse=True) and len(risks) == 4
    assert t["open_cases"] == 0 and t["escalated_cases"] == 0 and s["latest_activity"] == []


def test_dashboard_and_overview_purpose_filter_composes_with_scope(client, populated):
    p = populated
    manual = client.get("/api/v1/dashboard/stats", params={"brand_id": p.bid, "provenance": "manual"}, headers=p.h)
    assert manual.status_code == 200
    manual_data = manual.json()
    assert manual_data["totals"]["monitored_entities"] == 4
    assert sum(manual_data["risk_distribution"].values()) == 4
    assert manual_data["data_provenance"] == {"collected": 0, "manual": 4, "synthetic": 0}

    synthetic = client.get("/api/v1/dashboard/stats", params={"provenance": "synthetic"}, headers=p.h).json()
    assert synthetic["totals"]["monitored_entities"] == 1
    assert synthetic["entity_type_distribution"]["mobile_app"] == 1

    overview = client.get("/api/v1/reports/overview", params={"brand_id": p.bid, "provenance": "manual"}, headers=p.h)
    assert overview.status_code == 200
    report = overview.json()
    assert report["totals"]["entities"] == 4
    assert report["totals"]["detections"] == 3
    assert report["mobile_apps"]["total"] == 0
    # Cases do not carry a provenance field, so their workflow totals remain brand scoped.
    assert "Case workflow counts remain scope-wide" in " ".join(report["data_notes"])

    csv = client.get("/api/v1/reports/export/csv", params={"report": "entities", "brand_id": p.bid, "provenance": "synthetic"}, headers=p.h)
    assert csv.status_code == 200 and "com.acmebank.rewards" in csv.text
    assert "gardening_fan" not in csv.text

    invalid = client.get("/api/v1/reports/overview", params={"provenance": "invented"}, headers=p.h)
    assert invalid.status_code == 422


def test_dashboard_case_counts_and_activity_follow_workflow(client, populated):
    p = populated
    ids = [p.ents["p"]["id"], p.ents["w"]["id"]]
    c1 = client.post("/api/v1/cases", headers=p.h, json={"brand_id": p.bid, "title": "Case one here", "entity_ids": ids}).json()["id"]
    c2 = client.post("/api/v1/cases", headers=p.h, json={"brand_id": p.bid, "title": "Case two here", "entity_ids": [p.ents["a"]["id"]]}).json()["id"]
    for cid in (c1, c2):
        client.post(f"/api/v1/cases/{cid}/status", headers=p.h, json={"status": "triaged"})
        client.post(f"/api/v1/cases/{cid}/status", headers=p.h, json={"status": "under_review"})
        client.post(f"/api/v1/cases/{cid}/assign", headers=p.h, json={"assignee_id": str(p.w.users["inv"].id)})
    client.post(f"/api/v1/cases/{c1}/escalate", headers=p.h, json={"partner_type": "legal", "reason": "legal review needed"})
    client.post(f"/api/v1/cases/{c2}/resolve", headers=p.h, json={"outcome": "false_positive", "summary": "Sample app is benign."})
    s = client.get("/api/v1/dashboard/stats", headers=p.h).json()
    assert s["totals"]["open_cases"] == 1 and s["totals"]["escalated_cases"] == 1 and s["totals"]["resolved_cases"] == 1 and s["totals"]["unassigned_open_cases"] == 0
    assert s["case_status_distribution"]["escalated"] == 1 and s["case_status_distribution"]["resolved"] == 1
    assert s["latest_activity"][0]["event_type"] == "resolved" and {a["case_number"][:8] for a in s["latest_activity"]} == {"NN-2026-"}
    brand_scoped = client.get("/api/v1/dashboard/stats", params={"brand_id": p.bid}, headers=p.h).json()
    assert brand_scoped["totals"] == s["totals"]


def test_dashboard_mobile_summary_never_claims_verification(client, populated):
    p = populated
    m = client.get("/api/v1/dashboard/mobile-apps", headers=p.h).json()
    assert m["total_apps"] == 1 and "publisher_verified is always false" in m["note"]
    app = m["apps"][0]
    assert app["package_id"] == "com.acmebank.rewards" and app["publisher_verified"] is False and app["permissions_status"] == "supplied_unverified"
    assert app["sensitive_permissions"] == ["READ_SMS", "SYSTEM_ALERT_WINDOW"] and app["permissions_count"] == 3 and app["provenance"] == "synthetic"
    assert app["risk_score"] is not None and app["severity"] in ("medium", "high", "critical") and app["linked_websites"]
    assert m["high_risk_apps"] == (1 if app["severity"] in ("high", "critical") else 0) and sum(m["by_severity"].values()) == 1
    bare = client.post("/api/v1/entities", headers=p.h, json={"brand_id": p.bid, "entity_type": "mobile_app", "attributes": {"app_name": "No Perms", "package_id": "com.no.perms"}}).json()["entity"]
    m2 = client.get("/api/v1/dashboard/mobile-apps", headers=p.h).json()
    assert next(a for a in m2["apps"] if a["id"] == bare["id"])["permissions_status"] == "not_provided"
    assert client.get("/api/v1/dashboard/mobile-apps", headers=p.w.h["outsider"]).json()["total_apps"] == 0


def test_dashboard_empty_and_scoped_for_new_org(client, f, world):
    s = client.get("/api/v1/dashboard/stats", headers=world.h["inv"]).json()
    assert s["totals"]["monitored_entities"] == 0 and s["recent_detections"] == [] and s["risk_distribution"]["unknown"] == 0


def test_audit_scoping_filters_and_no_secrets(client, f, world):
    h = world.h["inv"]
    e = f.website(h, world.brand["id"])
    client.post(f"/api/v1/entities/{e['id']}/analyze", headers=h)
    uid = world.users["owner"].id
    client.patch(f"/api/v1/users/{uid}", headers=world.h["admin"], json={"password": "Another-Passw0rd!", "full_name": "Renamed"})
    mine = client.get("/api/v1/audit", params={"page_size": 100}, headers=h).json()
    assert mine["total"] > 0 and all(x["organization_id"] == str(world.org_a.id) for x in mine["items"])
    assert {"entity.create", "entity.analyze", "brand.create", "brand.reference_add"} <= {x["action"] for x in mine["items"]}
    other = client.get("/api/v1/audit", params={"page_size": 100}, headers=world.h["outsider"]).json()["items"]
    assert other and all(x["organization_id"] == str(world.org_b.id) for x in other)                          # only org B's own rows
    assert not any(x["resource_id"] == e["id"] for x in other)                                                 # nothing about org A's entity
    full = client.get("/api/v1/audit", params={"page_size": 100}, headers=world.h["admin"]).json()
    assert full["total"] > mine["total"] and any(x["action"] == "auth.login" for x in full["items"])
    blob = str(full["items"]).lower()
    assert "another-passw0rd" not in blob and "$2b$" not in blob and "bearer" not in blob
    upd = next(x for x in full["items"] if x["action"] == "user.update")
    assert upd["details"]["password_changed"] is True and upd["actor_email"] == world.users["admin"].email
    assert client.get("/api/v1/audit", params={"action": "entity."}, headers=h).json()["total"] >= 2
    assert client.get("/api/v1/audit", params={"resource_type": "entity", "resource_id": e["id"]}, headers=h).json()["total"] >= 2
    assert client.get("/api/v1/audit", params={"since": "2999-01-01T00:00:00Z"}, headers=h).json()["total"] == 0


def test_failed_login_is_audited(client, f, world):
    client.post("/api/v1/auth/login", json={"email": world.users["inv"].email, "password": "Wrong-Passw0rd!"})
    items = client.get("/api/v1/audit", params={"action": "auth.login_failed"}, headers=world.h["admin"]).json()["items"]
    assert len(items) == 1 and "wrong" not in str(items[0]).lower()


# ---------------- migrations / platform ----------------
def test_migrations_roundtrip_and_no_drift():
    if not _db_is_available():
        pytest.skip("Test database not reachable")
    cfg = alembic_cfg()
    eng = create_engine(_TEST_URL)
    try:
        with eng.connect() as c:
            diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
        assert diff == [], f"models and migrations differ: {diff}"
        command.downgrade(cfg, "base")
        with eng.connect() as c:
            assert set(inspect(c).get_table_names()) <= {"alembic_version"}
            assert c.execute(text("select count(*) from pg_class where relname='case_number_seq'")).scalar() == 0
        command.upgrade(cfg, "head")
        with eng.connect() as c:
            tables = set(inspect(c).get_table_names())
            assert set(Base.metadata.tables) <= tables
            ix = {i["name"] for i in inspect(c).get_indexes("digital_entities")}
            assert "ix_entities_brand_type" in ix and "ix_entities_risk" in ix
            uq = {u["name"] for u in inspect(c).get_unique_constraints("digital_entities")}
            assert "uq_entities_brand_type_canonical" in uq
            assert c.execute(text("select nextval('case_number_seq')")).scalar() == 1
    finally:
        eng.dispose()


def test_database_constraints_enforced(db, f, world):
    from sqlalchemy.exc import IntegrityError
    from app.models import EntityRelationship, DigitalEntity
    import uuid
    e = f.website(world.h["inv"], world.brand["id"])
    with pytest.raises(IntegrityError):
        db.add(EntityRelationship(source_entity_id=uuid.UUID(e["id"]), target_entity_id=uuid.UUID(e["id"]), relationship_type="shares_domain", confidence=0.5, evidence_note="x"))
        db.commit()
    db.rollback()
    e2 = f.website(world.h["inv"], world.brand["id"], url="https://second-site.xyz")
    a, b = sorted([uuid.UUID(e["id"]), uuid.UUID(e2["id"])])
    with pytest.raises(IntegrityError):                               # reversed canonical order is rejected by the CHECK constraint
        db.add(EntityRelationship(source_entity_id=b, target_entity_id=a, relationship_type="shares_domain", confidence=0.5, evidence_note="x"))
        db.commit()
    db.rollback()
    with pytest.raises(IntegrityError):
        db.add(EntityRelationship(source_entity_id=a, target_entity_id=b, relationship_type="shares_domain", confidence=1.5, evidence_note="x"))
        db.commit()


def test_health_and_ready(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    r = client.get("/api/v1/ready").json()
    from app.main import expected_head, _ROOT
    assert r["status"] == "ready" and r["migration_revision"] == expected_head()
    # the shipped head must be the newest revision file in alembic/versions/
    revisions = [f for f in (_ROOT / "alembic" / "versions").glob("*.py") if not f.name.startswith("_")]
    assert len(revisions) >= 3  # 0001 initial, 0002 ops tables, 0003+ extensions
    assert expected_head() in {f.stem.split("_")[1] for f in revisions}


def test_ready_reports_503_when_not_migrated(client):
    if not _db_is_available():
        pytest.skip("Test database not reachable")
    eng = create_engine(_TEST_URL)
    command.downgrade(alembic_cfg(), "base")
    try:
        r = client.get("/api/v1/ready")
        assert r.status_code == 503 and r.json()["status"] == "unavailable"
    finally:
        command.upgrade(alembic_cfg(), "head")
        eng.dispose()


def test_consistent_error_format(client, world):
    h = world.h["inv"]
    for r in (client.get("/api/v1/entities/00000000-0000-0000-0000-000000000000", headers=h), client.get("/api/v1/nope"), client.get("/api/v1/auth/me"),
              client.get("/api/v1/users", headers=h), client.post("/api/v1/entities", headers=h, json={}), client.get("/api/v1/entities/not-a-uuid", headers=h)):
        body = r.json()
        assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"} and isinstance(body["error"]["code"], str)
    v = client.post("/api/v1/entities", headers=h, json={}).json()["error"]
    assert v["code"] == "validation_error" and {d["field"] for d in v["details"]} >= {"brand_id", "entity_type"}
    assert client.get("/api/v1/entities/00000000-0000-0000-0000-000000000000", headers=h).status_code == 404
    assert client.put("/api/v1/entities", headers=h).status_code == 405


def test_unhandled_errors_do_not_leak_internals(world, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import dashboard
    monkeypatch.setattr(dashboard, "stats", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret db password=hunter2")))
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/dashboard/stats", headers=world.h["inv"])
    assert r.status_code == 500 and r.json()["error"] == {"code": "internal_error", "message": "Internal server error", "details": None} and "hunter2" not in r.text


def test_openapi_is_accurate_and_leak_free(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p in ("/api/v1/auth/login", "/api/v1/brands", "/api/v1/entities", "/api/v1/entities/{entity_id}/analyze", "/api/v1/evidence/upload", "/api/v1/detection/signals",
              "/api/v1/graph", "/api/v1/graph/clusters", "/api/v1/cases", "/api/v1/cases/{case_id}/escalate", "/api/v1/cases/{case_id}/resolve", "/api/v1/dashboard/stats",
              "/api/v1/dashboard/mobile-apps", "/api/v1/audit", "/api/v1/health", "/api/v1/ready", "/api/v1/collection/connectors"):
        assert p in paths, p
    blob = str(spec["components"]["schemas"]).lower()
    assert "hashed_password" not in blob and "secret_key" not in blob and "jwt" not in blob     # (client_secret is the standard OAuth2 form field)
    params = {p["name"]: p["schema"] for p in paths["/api/v1/entities"]["get"]["parameters"]}
    assert params["page_size"]["maximum"] == 100 and params["page"]["minimum"] == 1
    assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]
    assert client.get("/docs").status_code == 200 and client.get("/redoc").status_code == 200


def test_security_headers_and_cors(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    ok = client.options("/api/v1/entities", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/api/v1/entities", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_migration_0006_backfills_personal_scope(db, f, monkeypatch):
    """Migration 0006 scopes organization-less non-admin accounts (personal org + brand "Self").

    Additive only: admins and already-scoped users are untouched, and downgrade deletes nothing.
    """
    import importlib.util
    from pathlib import Path

    from app.models import Brand, Organization, User
    from app.models.enums import UserRole

    orgless = f.user(UserRole.INVESTIGATOR)   # account created before 0006 (public signup)
    admin = f.user(UserRole.ADMIN)            # global access - must stay untouched
    a = f.org("Org A")
    scoped = f.user(UserRole.BRAND_OWNER, a)  # already scoped - must stay untouched

    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*_0006_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0006", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    conn = db.connection()

    class _Op:
        def get_bind(self):
            return conn

    monkeypatch.setattr(mod, "op", _Op())
    mod.upgrade()

    db.refresh(orgless)
    assert orgless.organization_id is not None
    org = db.get(Organization, orgless.organization_id)
    assert org is not None and org.name == "Personal"
    assert [b.name for b in db.query(Brand).where(Brand.organization_id == org.id).all()] == ["Self"]

    assert admin.organization_id is None
    assert scoped.organization_id == a.id
    assert db.query(Organization).count() == 2 and db.query(User).count() == 3

    mod.downgrade()  # documented no-op: must not delete organizations/brands/users
    assert db.query(Organization).count() == 2 and db.query(Brand).count() == 1 and db.query(User).count() == 3
