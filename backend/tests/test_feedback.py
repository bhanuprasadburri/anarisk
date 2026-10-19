"""Feedback API: submission with scope validation, admin-only view, status workflow."""
from __future__ import annotations

from app.models import Feedback
from app.models.enums import FeedbackCategory, FeedbackStatus


def _make_case(client, world, f, title="Feedback case"):
    h = world.h["inv"]
    ent = f.profile(world.h["owner"], world.brand["id"])
    r = client.post("/api/v1/cases", headers=h, json={
        "brand_id": world.brand["id"],
        "title": title,
        "summary": "case linked from feedback",
        "entity_ids": [ent["id"]],
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_submit_feedback_persists_with_brand_and_case(client, world, f, db):
    case = _make_case(client, world, f)
    r = client.post("/api/v1/feedback", headers=world.h["inv"], json={
        "category": "bug",
        "message": "The evidence upload rejects valid PNGs larger than 2 MB.",
        "page_ref": "/investigate",
        "brand_id": world.brand["id"],
        "related_case_id": case["id"],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["category"] == "bug" and body["status"] == "open"
    assert body["brand_id"] == world.brand["id"] and body["related_case_id"] == case["id"]
    assert body["user_email"] == world.users["inv"].email

    row = db.query(Feedback).one()
    assert row.user_id == world.users["inv"].id and row.organization_id == world.org_a.id
    assert row.message == "The evidence upload rejects valid PNGs larger than 2 MB."


def test_submit_feedback_without_brand_is_allowed(client, world):
    r = client.post("/api/v1/feedback", headers=world.h["partner"], json={
        "category": "feature", "message": "Export cases to CSV please.",
    })
    assert r.status_code == 201 and r.json()["brand_id"] is None


def test_submit_feedback_rejects_out_of_scope_brand_and_case(client, world, f):
    case = _make_case(client, world, f)
    h = world.h["outsider"]  # org B: cannot reference org A's brand or case
    for payload in (
        {"category": "bug", "message": "x", "brand_id": world.brand["id"]},
        {"category": "bug", "message": "x", "related_case_id": case["id"]},
        {"category": "bug", "message": "x", "brand_id": "00000000-0000-0000-0000-000000000000"},
    ):
        r = client.post("/api/v1/feedback", headers=h, json=payload)
        assert r.status_code == 404, r.text


def test_submit_feedback_validation_and_auth(client, world):
    assert client.post("/api/v1/feedback", json={"category": "bug", "message": "x"}).status_code == 401
    h = world.h["inv"]
    assert client.post("/api/v1/feedback", headers=h, json={"category": "bug", "message": ""}).status_code == 422
    assert client.post("/api/v1/feedback", headers=h, json={"category": "nope", "message": "x"}).status_code == 422
    assert client.post("/api/v1/feedback", headers=h, json={"category": "bug", "message": "y" * 4001}).status_code == 422
    assert client.post("/api/v1/feedback", headers=h, json={"category": "bug", "message": "x" * 600, "page_ref": "p" * 501}).status_code == 422


def test_feedback_view_is_admin_only(client, world):
    client.post("/api/v1/feedback", headers=world.h["inv"], json={"category": "bug", "message": "visible"})
    for name in ("inv", "owner", "partner", "outsider"):
        assert client.get("/api/v1/feedback", headers=world.h[name]).status_code == 403, name
    r = client.get("/api/v1/feedback", headers=world.h["admin"])
    assert r.status_code == 200 and r.json()["total"] == 1
    assert r.json()["items"][0]["user_email"] == world.users["inv"].email


def test_feedback_admin_view_spans_organizations_with_filters(client, world):
    client.post("/api/v1/feedback", headers=world.h["inv"], json={"category": "bug", "message": "org A bug"})
    client.post("/api/v1/feedback", headers=world.h["outsider"], json={"category": "feature", "message": "org B idea"})
    h = world.h["admin"]

    all_rows = client.get("/api/v1/feedback", headers=h).json()
    assert all_rows["total"] == 2  # global admin triage across both organizations

    assert client.get("/api/v1/feedback?category=feature", headers=h).json()["items"][0]["message"] == "org B idea"
    assert client.get("/api/v1/feedback?status=open", headers=h).json()["total"] == 2
    assert client.get("/api/v1/feedback?status=resolved", headers=h).json()["total"] == 0


def test_feedback_status_workflow_admin_only(client, world):
    fid = client.post("/api/v1/feedback", headers=world.h["inv"], json={"category": "content", "message": "typo"}).json()["id"]

    # non-admins cannot change state
    assert client.patch(f"/api/v1/feedback/{fid}", headers=world.h["inv"], json={"status": "resolved"}).status_code == 403

    r = client.patch(f"/api/v1/feedback/{fid}", headers=world.h["admin"], json={"status": "resolved"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert client.get("/api/v1/feedback?status=resolved", headers=world.h["admin"]).json()["total"] == 1

    # idempotent update + honest 404s
    assert client.patch(f"/api/v1/feedback/{fid}", headers=world.h["admin"], json={"status": "resolved"}).status_code == 200
    assert client.patch("/api/v1/feedback/00000000-0000-0000-0000-000000000000", headers=world.h["admin"], json={"status": "open"}).status_code == 404
    assert client.patch(f"/api/v1/feedback/{fid}", headers=world.h["admin"], json={"status": "bogus"}).status_code == 422
    assert client.get("/api/v1/feedback", headers=world.h["admin"]).json()["items"][0]["user_email"] == world.users["inv"].email


def test_feedback_scoped_states_enumerated(client, world):
    # the CHECK constraints store enum values exactly as the API exposes them
    fid = client.post("/api/v1/feedback", headers=world.h["owner"], json={"category": "other", "message": "misc"}).json()["id"]
    client.patch(f"/api/v1/feedback/{fid}", headers=world.h["admin"], json={"status": "resolved"})
    from app.db.session import get_sessionmaker
    db = get_sessionmaker()()
    try:
        row = db.query(Feedback).one()
        assert row.category == FeedbackCategory.OTHER and row.status == FeedbackStatus.RESOLVED
    finally:
        db.close()
