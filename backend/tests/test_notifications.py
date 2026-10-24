"""Notifications API: list, unread counts, mark read (single and bulk), delete, broadcast, scoping."""
from __future__ import annotations


def _make_case(client, world, f, title="Notification case"):
    """Create a case as the investigator (creator) and return it."""
    h = world.h["inv"]
    brand = world.brand  # the world fixture's brand (org A)
    ent = f.profile(world.h["owner"], brand["id"])
    r = client.post(
        "/api/v1/cases",
        headers=h,
        json={
            "brand_id": brand["id"],
            "title": title,
            "summary": "created to exercise the notification workflow",
            "entity_ids": [ent["id"]],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_notifications_empty_then_created(client, world, f):
    h = world.h["inv"]
    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "unread_count", "page", "page_size", "pages"}
    assert body["total"] == 0
    assert body["unread_count"] == 0

    # Creating a case then triaging it notifies the creator (and admins).
    case = _make_case(client, world, f)
    r = client.post(
        f"/api/v1/cases/{case['id']}/status",
        headers=h,
        json={"status": "triaged", "comment": "looks real"},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert r.json()["unread_count"] >= 1
    item = r.json()["items"][0]
    for key in ("id", "type", "title", "is_read", "created_at"):
        assert key in item, f"missing {key}"


def test_high_risk_alert_is_per_assessment_and_persistently_deduplicated(client, world, f, db):
    from sqlalchemy import select

    from app.models import HighRiskAlert, Notification, RiskAssessment
    from app.models.enums import Severity
    from app.services.notifications import notify_high_risk

    entity = f.website(world.h["owner"], world.brand["id"], url="https://acmebank-login.top/verify")
    assessment = RiskAssessment(
        entity_id=entity["id"], model_version="test-rule-v1", configured_weights={}, effective_weights={},
        component_scores={}, risk_score=0.9, confidence_score=0.4, confidence_breakdown={},
        severity=Severity.HIGH, thresholds={}, is_synthetic=False,
    )
    db.add(assessment)
    db.flush()
    from app.models import DigitalEntity
    entity_row = db.get(DigitalEntity, entity["id"])

    assert notify_high_risk(db, entity_row, assessment) >= 1
    assert notify_high_risk(db, entity_row, assessment) == 0
    alerts = list(db.scalars(select(HighRiskAlert).where(HighRiskAlert.assessment_id == assessment.id)))
    assert len(alerts) == 1 and alerts[0].rule_version == "test-rule-v1" and alerts[0].risk_score == 0.9
    notice = db.scalar(select(Notification).where(Notification.type == "high_risk_detection"))
    assert notice.resource_type == "detection_alert" and str(assessment.id) in notice.link_url


def test_high_risk_alert_excludes_verified_official_assets(client, world, f, db):
    from sqlalchemy import select

    from app.models import HighRiskAlert, RiskAssessment
    from app.models.enums import Severity
    from app.services.notifications import notify_high_risk

    entity = f.website(world.h["owner"], world.brand["id"], url="https://acmebank.example/")
    assessment = RiskAssessment(
        entity_id=entity["id"], model_version="test-rule-v1", configured_weights={}, effective_weights={},
        component_scores={}, risk_score=0.95, confidence_score=0.4, confidence_breakdown={},
        severity=Severity.CRITICAL, thresholds={}, is_synthetic=False,
    )
    db.add(assessment)
    db.flush()
    from app.models import DigitalEntity
    entity_row = db.get(DigitalEntity, entity["id"])
    assert notify_high_risk(db, entity_row, assessment) == 0
    assert db.scalar(select(HighRiskAlert.id).where(HighRiskAlert.assessment_id == assessment.id)) is None


def test_assignment_notifies_the_assignee(client, world, f):
    h = world.h["inv"]
    case = _make_case(client, world, f, title="assign me")
    # detected -> triaged -> under_review, then assign to the investigator.
    r = client.post(
        f"/api/v1/cases/{case['id']}/status", headers=h, json={"status": "triaged"}
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/v1/cases/{case['id']}/status", headers=h, json={"status": "under_review"}
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/v1/cases/{case['id']}/assign",
        headers=h,
        json={"assignee_id": str(world.users["inv"].id)},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200
    types = {n["type"] for n in r.json()["items"]}
    assert "case_assigned" in types


def test_notifications_unread_count_and_mark_read(client, world, f):
    h = world.h["inv"]
    case = _make_case(client, world, f, title="mark me")
    client.post(
        f"/api/v1/cases/{case['id']}/status", headers=h, json={"status": "triaged"}
    )
    client.post(
        f"/api/v1/cases/{case['id']}/status", headers=h, json={"status": "under_review"}
    )

    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "expected at least one notification"
    unread_before = r.json()["unread_count"]
    assert unread_before >= 1

    # Mark exactly one as read.
    nid = next(n["id"] for n in items if not n["is_read"])
    r = client.post("/api/v1/notifications/read", headers=h, json={"ids": [nid]})
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    assert r.json()["unread_count"] == unread_before - 1

    # Mark ALL remaining as read.
    r = client.post("/api/v1/notifications/read", headers=h, json={})
    assert r.status_code == 200
    assert r.json()["updated"] >= 1
    assert r.json()["unread_count"] == 0

    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200
    assert all(n["is_read"] for n in r.json()["items"])

    # unread_only filter now returns nothing.
    r = client.get("/api/v1/notifications?unread_only=true", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_notifications_are_scoped_to_user(client, world, f):
    """A different user in the same org must not see the investigator's notifications."""
    inv_h = world.h["inv"]
    case = _make_case(client, world, f, title="scoped")
    client.post(
        f"/api/v1/cases/{case['id']}/status", headers=inv_h, json={"status": "triaged"}
    )

    # The owner (different user, same org) sees only their own notifications.
    r = client.get("/api/v1/notifications", headers=world.h["owner"])
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_notifications_require_auth(client):
    assert client.get("/api/v1/notifications").status_code == 401


def test_delete_notification_owner_and_cross_user(client, world, f):
    inv_h = world.h["inv"]
    case = _make_case(client, world, f, title="delete me")
    client.post(f"/api/v1/cases/{case['id']}/status", headers=inv_h, json={"status": "triaged"})
    nid = client.get("/api/v1/notifications", headers=inv_h).json()["items"][0]["id"]

    # another user (same org) cannot delete it: 404, and the row survives
    assert client.delete(f"/api/v1/notifications/{nid}", headers=world.h["owner"]).status_code == 404
    assert nid in [n["id"] for n in client.get("/api/v1/notifications", headers=inv_h).json()["items"]]

    # the owner deletes it, and it disappears from their list
    assert client.delete(f"/api/v1/notifications/{nid}", headers=inv_h).status_code == 204
    assert nid not in [n["id"] for n in client.get("/api/v1/notifications", headers=inv_h).json()["items"]]


def test_admin_can_delete_any_notification(client, world, f):
    inv_h = world.h["inv"]
    case = _make_case(client, world, f, title="admin delete")
    client.post(f"/api/v1/cases/{case['id']}/status", headers=inv_h, json={"status": "triaged"})
    nid = client.get("/api/v1/notifications", headers=inv_h).json()["items"][0]["id"]
    assert client.delete(f"/api/v1/notifications/{nid}", headers=world.h["admin"]).status_code == 204


def test_delete_notification_auth_and_format(client, world):
    assert client.delete("/api/v1/notifications/00000000-0000-0000-0000-000000000000").status_code == 401
    assert client.delete("/api/v1/notifications/not-a-uuid", headers=world.h["inv"]).status_code == 422
    assert client.delete(
        "/api/v1/notifications/00000000-0000-0000-0000-000000000000", headers=world.h["inv"]
    ).status_code == 404


def test_broadcast_reaches_every_active_user(client, world, f):
    f.user(world.users["inv"].role, world.org_a, active=False)  # inactive accounts receive nothing
    r = client.post(
        "/api/v1/notifications/broadcast", headers=world.h["admin"],
        json={"title": "Scheduled maintenance", "message": "The platform will be read-only on Sunday."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipients"] == body["created"] == 6  # world users, minus the inactive one
    # every active user (including the sender) sees the persisted row through the normal API
    for name, h in world.h.items():
        items = client.get("/api/v1/notifications", headers=h).json()["items"]
        assert any(n["type"] == "broadcast" and n["title"] == "Scheduled maintenance" for n in items), name


def test_broadcast_is_admin_only(client, world):
    for name in ("inv", "owner", "partner", "outsider"):
        r = client.post("/api/v1/notifications/broadcast", headers=world.h[name], json={"title": "x", "message": "y"})
        assert r.status_code == 403, name
    assert client.post("/api/v1/notifications/broadcast", json={"title": "x", "message": "y"}).status_code == 401


def test_broadcast_validates_input(client, world):
    h = world.h["admin"]
    assert client.post("/api/v1/notifications/broadcast", headers=h, json={"title": "", "message": "m"}).status_code == 422
    assert client.post("/api/v1/notifications/broadcast", headers=h, json={"title": "t", "message": ""}).status_code == 422
    assert client.post("/api/v1/notifications/broadcast", headers=h, json={"title": "t"}).status_code == 422
