import concurrent.futures

import pytest

from app.models.enums import UserRole


@pytest.fixture
def ctx(client, f, world):
    h, bid = world.h["inv"], world.brand["id"]
    e1 = f.website(h, bid, url="https://acmebank-bonus.top/claim")
    e2 = f.profile(h, bid, handle="acmebank_help_desk", bio="AcmeBank customer care", links=["https://acmebank-bonus.top/claim"])
    client.post("/api/v1/detection/analyze", headers=h, json={"brand_id": bid})
    class C: pass
    c = C(); c.w, c.h, c.bid, c.e1, c.e2 = world, h, bid, e1, e2
    c.inv2 = f.user(UserRole.INVESTIGATOR, world.org_a)
    c.h2 = f.headers(c.inv2)
    return c


def mk(client, c, **kw):
    r = client.post("/api/v1/cases", headers=c.h, json={"brand_id": c.bid, "title": "Fake bonus campaign", "summary": "s", "entity_ids": [c.e1["id"], c.e2["id"]], **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()


def status(client, c, cid, to, h=None, **kw):
    return client.post(f"/api/v1/cases/{cid}/status", headers=h or c.h, json={"status": to, **kw})


def to_under_review(client, c, cid):
    assert status(client, c, cid, "triaged").status_code == 200
    assert status(client, c, cid, "under_review").status_code == 200


def test_create_case_rollup_and_detail(client, ctx):
    case = mk(client, ctx)
    assert case["status"] == "detected" and case["case_number"].startswith("NN-2026-") and case["entity_count"] == 2
    assert case["severity"] in ("medium", "high", "critical") and 0 < case["risk_score"] <= 1 and 0 <= case["confidence"] <= 1
    top = max(client.get(f"/api/v1/entities/{e['id']}", headers=ctx.h).json()["current_risk_score"] for e in (ctx.e1, ctx.e2))
    assert case["risk_score"] == top                                                          # case risk = highest member risk
    assert case["risk_assessment"]["risk_score"] == top and len(case["risk_assessment"]["signals"]) == 4
    for ce in case["entities"]:
        assert ce["latest_assessment"]["signals"] and ce["role"] in ("subject", "related")
    assert {ce["role"] for ce in case["entities"]} == {"subject", "related"}
    assert case["events"][0]["event_type"] == "created" and case["events"][0]["to_status"] == "detected"
    assert case["allowed_transitions"] == ["triaged"] and case["assigned_to"] is None and case["created_by"]["email"]


def test_create_validations(client, ctx):
    assert client.post("/api/v1/cases", headers=ctx.h, json={"brand_id": ctx.bid, "title": "x", "entity_ids": [ctx.e1["id"]]}).status_code == 422
    assert client.post("/api/v1/cases", headers=ctx.h, json={"brand_id": ctx.bid, "title": "Valid title", "entity_ids": []}).status_code == 422
    assert client.post("/api/v1/cases", headers=ctx.h, json={"brand_id": ctx.bid, "title": "Valid title", "entity_ids": ["00000000-0000-0000-0000-000000000000"]}).status_code == 404


def test_idempotency_key_prevents_duplicate_cases(client, ctx):
    first = client.post("/api/v1/cases", headers={**ctx.h, "Idempotency-Key": "abc-123"}, json={"brand_id": ctx.bid, "title": "Same request", "entity_ids": [ctx.e1["id"]]})
    second = client.post("/api/v1/cases", headers={**ctx.h, "Idempotency-Key": "abc-123"}, json={"brand_id": ctx.bid, "title": "Same request", "entity_ids": [ctx.e1["id"]]})
    assert first.status_code == 201 and second.status_code == 200 and first.json()["id"] == second.json()["id"]
    assert client.get("/api/v1/cases", headers=ctx.h).json()["total"] == 1
    other = client.post("/api/v1/cases", headers={**ctx.h2, "Idempotency-Key": "abc-123"}, json={"brand_id": ctx.bid, "title": "Other user", "entity_ids": [ctx.e1["id"]]})
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]               # keys are per user


def test_full_workflow_detected_to_resolved(client, ctx):
    cid = mk(client, ctx)["id"]
    assert status(client, ctx, cid, "triaged").json()["status"] == "triaged"
    assert status(client, ctx, cid, "under_review", comment="Evidence checked").json()["status"] == "under_review"
    assigned = client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["inv"].id), "note": "mine"}).json()
    assert assigned["status"] == "assigned" and assigned["assigned_to"]["email"] == ctx.w.users["inv"].email and len(assigned["assignments"]) == 1
    esc = client.post(f"/api/v1/cases/{cid}/escalate", headers=ctx.h, json={"partner_type": "legal", "partner_contact": "legal@acme.example", "reason": "Credential harvesting link", "requested_action": "Takedown review"}).json()
    assert esc["status"] == "escalated" and esc["escalated_at"] and esc["escalations"][0]["partner_type"] == "legal" and esc["escalation_summary"].startswith("legal:")
    assert any("no external takedown" in str(e["details"]).lower() for e in esc["events"] if e["event_type"] == "escalated")
    res = client.post(f"/api/v1/cases/{cid}/resolve", headers=ctx.h, json={"outcome": "confirmed_threat_actioned", "summary": "Legal sent takedown; site offline."}).json()
    assert res["status"] == "resolved" and res["resolved_at"] and res["resolved_by"]["email"] and res["resolution_outcome"] == "confirmed_threat_actioned"
    kinds = [(e["event_type"], e["from_status"], e["to_status"]) for e in res["events"]]
    assert ("created", None, "detected") in kinds and ("status_changed", "detected", "triaged") in kinds and ("status_changed", "triaged", "under_review") in kinds
    assert ("status_changed", "under_review", "assigned") in kinds and ("escalated", "assigned", "escalated") in kinds and ("resolved", "escalated", "resolved") in kinds
    assert any("Evidence checked" in n["body"] for n in res["notes"]) and res["allowed_transitions"] == []


def test_invalid_transitions_rejected_with_allowed_list(client, ctx):
    cid = mk(client, ctx)["id"]
    for bad in ("under_review", "assigned", "escalated", "resolved"):
        r = status(client, ctx, cid, bad)
        assert r.status_code in (409, 422), bad
    r = status(client, ctx, cid, "under_review")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition" and r.json()["error"]["details"]["allowed"] == ["triaged"]
    assert status(client, ctx, cid, "detected").status_code == 409
    assert status(client, ctx, cid, "nonsense").status_code == 422
    assert client.get(f"/api/v1/cases/{cid}", headers=ctx.h).json()["status"] == "detected"        # nothing changed


def test_assigned_requires_owner_and_escalated_requires_handoff(client, ctx):
    cid = mk(client, ctx)["id"]
    to_under_review(client, ctx, cid)
    assert status(client, ctx, cid, "assigned").status_code == 422                                  # allowed transition, but needs an owner
    r = status(client, ctx, cid, "escalated")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"               # cannot jump to escalated from under_review
    r = client.post(f"/api/v1/cases/{cid}/escalate", headers=ctx.h, json={"partner_type": "legal", "reason": "needs legal"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"            # needs an owner first


def test_assignment_rules_and_reassignment_history(client, ctx):
    cid = mk(client, ctx)["id"]
    me, other = str(ctx.w.users["inv"].id), str(ctx.inv2.id)
    assert client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": me}).status_code == 409   # too early (detected)
    to_under_review(client, ctx, cid)
    assert client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["partner"].id)}).status_code == 422
    assert client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["owner"].id)}).status_code == 422
    assert client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    a1 = client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": me}).json()
    same = client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": me}).json()
    assert same["version"] == a1["version"] and len(same["assignments"]) == 1                      # idempotent repeat
    re_ = client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": other, "note": "handover"}).json()
    assert re_["status"] == "assigned" and re_["assigned_to"]["id"] == other
    assert [a["unassigned_at"] is not None for a in re_["assignments"]] == [True, False]           # history kept, one open row
    assert any(e["event_type"] == "reassigned" for e in re_["events"])
    assert client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.w.h["owner"], json={"assignee_id": me}).status_code == 403
    assert client.get("/api/v1/cases", params={"assignee_id": other}, headers=ctx.h).json()["total"] == 1
    assert client.get("/api/v1/cases", params={"mine": True}, headers=ctx.h2).json()["total"] == 1
    assert client.get("/api/v1/cases", params={"mine": True}, headers=ctx.h).json()["total"] == 0
    assert {u["email"] for u in client.get("/api/v1/users/assignable", headers=ctx.h).json()} >= {ctx.inv2.email, ctx.w.users["inv"].email}


def test_resolution_requires_outcome_and_summary_and_shortcuts(client, ctx):
    cid = mk(client, ctx)["id"]
    status(client, ctx, cid, "triaged")
    assert status(client, ctx, cid, "resolved").status_code == 422
    assert status(client, ctx, cid, "resolved", resolution_outcome="false_positive").status_code == 422
    r = status(client, ctx, cid, "resolved", resolution_outcome="false_positive", resolution_summary="Fan page, not impersonation.")   # documented shortcut
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert client.post(f"/api/v1/cases/{cid}/resolve", headers=ctx.h, json={"outcome": "duplicate", "summary": "duplicate of another case"}).status_code == 409   # already resolved
    assert client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["inv"].id)}).status_code == 409


def test_reopen_requires_admin_and_comment(client, ctx):
    cid = mk(client, ctx)["id"]
    status(client, ctx, cid, "triaged")
    status(client, ctx, cid, "resolved", resolution_outcome="inconclusive", resolution_summary="Not enough evidence yet.")
    assert status(client, ctx, cid, "under_review").status_code == 403                              # investigator cannot reopen
    assert status(client, ctx, cid, "under_review", h=ctx.w.h["admin"]).status_code == 422          # comment required
    r = status(client, ctx, cid, "under_review", h=ctx.w.h["admin"], comment="New evidence arrived")
    d = r.json()
    assert r.status_code == 200 and d["status"] == "under_review" and d["resolved_at"] is None and d["resolution_summary"] is None
    assert any(e["event_type"] == "reopened" for e in d["events"])


def test_duplicate_and_racing_status_requests_are_safe(client, ctx):
    cid = mk(client, ctx)["id"]
    ok = status(client, ctx, cid, "triaged", expected_status="detected")
    dup = status(client, ctx, cid, "triaged", expected_status="detected")
    assert ok.status_code == 200 and dup.status_code == 409 and dup.json()["error"]["code"] == "status_conflict"
    again = status(client, ctx, cid, "triaged")
    assert again.status_code == 409 and again.json()["error"]["code"] == "no_change"
    cid2 = mk(client, ctx)["id"]
    def go(_):
        return status(client, ctx, cid2, "triaged", expected_status="detected").status_code
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        codes = sorted(ex.map(go, range(6)))
    assert codes.count(200) == 1 and codes.count(409) == 5                                           # row lock: exactly one wins
    d = client.get(f"/api/v1/cases/{cid2}", headers=ctx.h).json()
    assert [e["to_status"] for e in d["events"]].count("triaged") == 1


def test_notes_and_status_history_and_permissions(client, ctx):
    cid = mk(client, ctx)["id"]
    n = client.post(f"/api/v1/cases/{cid}/notes", headers=ctx.h, json={"body": "Called the registrar."})
    assert n.status_code == 201 and n.json()["author"]["email"] == ctx.w.users["inv"].email and n.json()["created_at"]
    assert client.post(f"/api/v1/cases/{cid}/notes", headers=ctx.h, json={"body": ""}).status_code == 422
    assert client.post(f"/api/v1/cases/{cid}/notes", headers=ctx.w.h["owner"], json={"body": "owner comment"}).status_code == 201
    d = client.get(f"/api/v1/cases/{cid}", headers=ctx.h).json()
    assert [x["body"] for x in d["notes"]] == ["Called the registrar.", "owner comment"] and sum(e["event_type"] == "note_added" for e in d["events"]) == 2


def test_partner_sees_only_escalated_cases_and_can_add_notes(client, ctx):
    p = ctx.w.h["partner"]
    c1, c2 = mk(client, ctx)["id"], mk(client, ctx)["id"]
    to_under_review(client, ctx, c1)
    client.post(f"/api/v1/cases/{c1}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["inv"].id)})
    assert client.get("/api/v1/cases", headers=p).json()["total"] == 0 and client.get(f"/api/v1/cases/{c1}", headers=p).status_code == 404
    client.post(f"/api/v1/cases/{c1}/escalate", headers=ctx.h, json={"partner_type": "platform", "reason": "Report to platform trust & safety"})
    lst = client.get("/api/v1/cases", headers=p).json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == c1 and client.get(f"/api/v1/cases/{c2}", headers=p).status_code == 404
    assert client.post(f"/api/v1/cases/{c1}/notes", headers=p, json={"body": "Platform contact acknowledged."}).status_code == 201
    assert client.post(f"/api/v1/cases/{c1}/status", headers=p, json={"status": "resolved", "resolution_outcome": "duplicate", "resolution_summary": "nope nope"}).status_code == 403
    assert client.post(f"/api/v1/cases/{c1}/escalate", headers=p, json={"partner_type": "legal", "reason": "attempt"}).status_code == 403
    assert client.get("/api/v1/dashboard/stats", headers=p).status_code == 403


def test_escalating_again_adds_handoffs_without_new_status(client, ctx):
    cid = mk(client, ctx)["id"]
    to_under_review(client, ctx, cid)
    client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["inv"].id)})
    client.post(f"/api/v1/cases/{cid}/escalate", headers=ctx.h, json={"partner_type": "legal", "reason": "legal review"})
    d = client.post(f"/api/v1/cases/{cid}/escalate", headers=ctx.h, json={"partner_type": "marketing", "reason": "customer comms needed"}).json()
    assert d["status"] == "escalated" and [e["partner_type"] for e in d["escalations"]] == ["legal", "marketing"]
    back = status(client, ctx, cid, "assigned").json()                                                # de-escalation allowed by default config
    assert back["status"] == "assigned"


def test_list_filter_sort_paginate(client, ctx):
    ids = []
    for i in range(5):
        ids.append(mk(client, ctx, title=f"Case number {i}")["id"] if False else client.post("/api/v1/cases", headers=ctx.h, json={"brand_id": ctx.bid, "title": f"Case number {i}", "entity_ids": [ctx.e1["id"] if i % 2 else ctx.e2["id"]]}).json()["id"])
    status(client, ctx, ids[0], "triaged")
    p = client.get("/api/v1/cases", params={"page_size": 2, "page": 3}, headers=ctx.h).json()
    assert p["total"] == 5 and p["pages"] == 3 and len(p["items"]) == 1
    assert client.get("/api/v1/cases", params={"status": "triaged"}, headers=ctx.h).json()["total"] == 1
    assert client.get("/api/v1/cases", params={"status": ["triaged", "detected"]}, headers=ctx.h).json()["total"] == 5
    assert client.get("/api/v1/cases", params={"q": "number 3"}, headers=ctx.h).json()["total"] == 1
    assert client.get("/api/v1/cases", params={"unassigned": True, "open_only": True}, headers=ctx.h).json()["total"] == 5
    assert client.get("/api/v1/cases", params={"entity_id": ctx.e1["id"]}, headers=ctx.h).json()["total"] == 2
    asc = [c["case_number"] for c in client.get("/api/v1/cases", params={"sort": "case_number", "order": "asc"}, headers=ctx.h).json()["items"]]
    assert asc == sorted(asc)
    by_risk = [c["risk_score"] for c in client.get("/api/v1/cases", params={"sort": "risk_score", "order": "desc"}, headers=ctx.h).json()["items"]]
    assert by_risk == sorted(by_risk, reverse=True)
    by_sev = client.get("/api/v1/cases", params={"sort": "severity"}, headers=ctx.h)
    assert by_sev.status_code == 200
    assert client.get("/api/v1/cases", params={"sort": "bogus"}, headers=ctx.h).status_code == 422
    assert client.get("/api/v1/cases", params={"severity": ["critical"]}, headers=ctx.h).status_code == 200
    assert client.get("/api/v1/cases/workflow", headers=ctx.h).json()["transitions"]["detected"] == ["triaged"]


def test_add_entities_updates_rollup_and_blocks_on_resolved(client, ctx, f):
    cid = client.post("/api/v1/cases", headers=ctx.h, json={"brand_id": ctx.bid, "title": "Single entity case", "entity_ids": [ctx.e1["id"]]}).json()["id"]
    extra = f.website(ctx.h, ctx.bid, url="https://acmebank-wallet-claim.top/login", analyze=True) if False else f.website(ctx.h, ctx.bid, url="https://acmebank-wallet-claim.top/login")
    d = client.post(f"/api/v1/cases/{cid}/entities", headers=ctx.h, json=[{"entity_id": extra["id"], "role": "related"}])
    assert d.status_code == 200 and d.json()["entity_count"] == 2 and any(e["event_type"] == "entity_added" for e in d.json()["events"])
    status(client, ctx, cid, "triaged")
    status(client, ctx, cid, "resolved", resolution_outcome="duplicate", resolution_summary="dup of other")
    assert client.post(f"/api/v1/cases/{cid}/entities", headers=ctx.h, json=[{"entity_id": ctx.e2["id"]}]).status_code == 409


def test_audit_trail_records_significant_changes(client, ctx):
    cid = mk(client, ctx)["id"]
    to_under_review(client, ctx, cid)
    client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["inv"].id)})
    client.post(f"/api/v1/cases/{cid}/notes", headers=ctx.h, json={"body": "n"})
    client.post(f"/api/v1/cases/{cid}/escalate", headers=ctx.h, json={"partner_type": "legal", "reason": "legal please"})
    client.post(f"/api/v1/cases/{cid}/resolve", headers=ctx.h, json={"outcome": "confirmed_threat_actioned", "summary": "done and dusted"})
    a = client.get("/api/v1/audit", params={"resource_type": "case", "resource_id": cid, "page_size": 100}, headers=ctx.h).json()
    actions = [x["action"] for x in a["items"]]
    for expected in ("case.create", "case.status_change", "case.assign", "case.note", "case.escalate"):
        assert expected in actions, expected
    assert actions.count("case.status_change") == 3                                                  # triaged, under_review, resolved (assign/escalate have their own audit actions)
    assert all(x["actor_email"] and x["created_at"] for x in a["items"])


def test_case_platforms_persist_through_create_and_patch(client, ctx):
    case = mk(client, ctx, platforms=["x", "instagram"])
    assert case["platforms"] == ["x", "instagram"]
    # default: empty list, never null
    assert mk(client, ctx)["platforms"] == []

    cid = case["id"]
    r = client.patch(f"/api/v1/cases/{cid}", headers=ctx.h, json={"platforms": ["tiktok"]})
    assert r.status_code == 200 and r.json()["platforms"] == ["tiktok"]
    assert client.get(f"/api/v1/cases/{cid}", headers=ctx.h).json()["platforms"] == ["tiktok"]   # persisted on read

    # values are constrained to the PLATFORM_LABELS keys
    assert client.patch(f"/api/v1/cases/{cid}", headers=ctx.h, json={"platforms": ["myspace"]}).status_code == 422
    assert client.post("/api/v1/cases", headers=ctx.h, json={
        "brand_id": ctx.bid, "title": "bad platform", "entity_ids": [ctx.e1["id"]], "platforms": ["myspace"],
    }).status_code == 422

    # a patch without platforms leaves the stored tags untouched
    r = client.patch(f"/api/v1/cases/{cid}", headers=ctx.h, json={"title": "Renamed platform case"})
    assert r.status_code == 200
    assert r.json()["platforms"] == ["tiktok"] and r.json()["title"] == "Renamed platform case"


def test_case_graph_composed_server_side(client, ctx):
    cid = mk(client, ctx)["id"]
    g = client.get(f"/api/v1/cases/{cid}/graph", headers=ctx.h)
    assert g.status_code == 200, g.text
    body = g.json()
    assert set(body) == {"nodes", "edges", "node_count", "edge_count", "cluster_count"}
    assert {n["id"] for n in body["nodes"]} == {ctx.e1["id"], ctx.e2["id"]}
    assert body["edge_count"] == 0

    # a relationship among the case's entities shows up in the case sub-graph
    rel = client.post("/api/v1/graph/relationships", headers=ctx.h, json={
        "source_entity_id": ctx.e1["id"], "target_entity_id": ctx.e2["id"],
        "relationship_type": "shares_image", "confidence": 0.9, "evidence_note": "same creative",
    })
    assert rel.status_code in (200, 201), rel.text
    g2 = client.get(f"/api/v1/cases/{cid}/graph", headers=ctx.h).json()
    assert g2["node_count"] == 2 and g2["edge_count"] == 1 and g2["cluster_count"] == 1

    # read is case:read scoped: 401 unauthenticated, 404 out of scope (outsiders, unknown id)
    assert client.get(f"/api/v1/cases/{cid}/graph").status_code == 401
    assert client.get(f"/api/v1/cases/{cid}/graph", headers=ctx.w.h["outsider"]).status_code == 404
    assert client.get("/api/v1/cases/00000000-0000-0000-0000-000000000000/graph", headers=ctx.h).status_code == 404
    # partners only see cases handed off to them: 404 before escalation, readable after
    p = ctx.w.h["partner"]
    assert client.get(f"/api/v1/cases/{cid}/graph", headers=p).status_code == 404
    to_under_review(client, ctx, cid)
    client.post(f"/api/v1/cases/{cid}/assign", headers=ctx.h, json={"assignee_id": str(ctx.w.users["inv"].id)})
    esc = client.post(f"/api/v1/cases/{cid}/escalate", headers=ctx.h, json={"partner_type": "legal", "reason": "legal review"})
    assert esc.status_code in (200, 201), esc.text
    assert client.get(f"/api/v1/cases/{cid}/graph", headers=p).status_code == 200
