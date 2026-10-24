"""Detections feed extensions: /detections list, detail, re-analyze and the documented model rules."""
import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import PASSWORD, png_bytes


def _setup(f, w):
    """Brand with official logo + a few entities that get analyzed."""
    h = w.h
    r = f.client.post(f"/api/v1/brands/{w.brand['id']}/references/image", files={"file": ("logo.png", png_bytes("official"), "image/png")},
                      headers=h["owner"])
    assert r.status_code == 201, r.text
    e1 = f.profile(h["owner"], w.brand["id"], handle="acmebank_support_24", platform="x",
                   bio="Need help with your AcmeBank account? Message us your card number to verify.")
    e2 = f.website(h["owner"], w.brand["id"], url="https://acmebank-secure-login.top/verify")
    for eid in (e1["id"], e2["id"]):
        rr = f.client.post(f"/api/v1/entities/{eid}/analyze", headers=h["inv"])  # brand owner lacks entity:analyze
        assert rr.status_code == 201, rr.text
    return e1, e2


def test_detection_record_and_reference_verification(world, f):
    """Round 2 §2: the detection record carries the full observation window + the official asset it
    imitates, and every official reference records who verified it and when."""
    e1, e2 = _setup(f, world)
    h = world.h["inv"]
    items = f.client.get("/api/v1/detections", headers=h).json()["items"]
    item = next(x for x in items if x["entity"]["id"] == e1["id"])
    site = next(x for x in items if x["entity"]["id"] == e2["id"])

    # the observation window and where it was seen are exposed on the entity ref
    ent = item["entity"]
    assert ent["first_seen_at"] and ent["last_seen_at"]
    assert ent["first_seen_at"] <= ent["last_seen_at"]
    assert ent["source_url"] is None          # profile entities have no source url
    assert site["entity"]["source_url"] == "https://acmebank-secure-login.top/verify"

    # the detection names a real official asset it was measured against
    matched = item["matched_official_asset_id"]
    assert matched is not None and isinstance(matched, str)
    refs = f.client.get(f"/api/v1/brands/{world.brand['id']}", headers=world.h["owner"]).json()["references"]
    assert matched in {r["id"] for r in refs}

    # every official reference records who verified it and when
    for r in refs:
        assert r["verified_at"] is not None and r["verified_by"] is not None


def test_model_endpoint_documents_actual_rules(world, f):
    r = f.client.get("/api/v1/detection/model", headers=world.h["inv"])
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["model_version"]
    assert set(m["weights"]) == {"brand_logo", "impersonation", "url_risk", "behavior"}
    assert m["severity_thresholds"]["high"] > m["severity_thresholds"]["medium"]
    assert "synthetic_cap" in m["confidence"]
    rules = {x["signal_type"]: x["rules"] for x in m["rule_description"]}
    assert set(rules) == set(m["weights"])
    # the descriptions must be substantive plain-English, not placeholders
    assert all(len(v) > 120 for v in rules.values())
    assert "0.4" in rules["behavior"] and "UNAVAILABLE" in rules["brand_logo"]


def test_detections_list_filters_sort_and_detail(world, f):
    e1, e2 = _setup(f, world)
    h = world.h["inv"]
    r = f.client.get("/api/v1/detections", headers=h)
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 2
    item = next(x for x in page["items"] if x["entity"]["id"] == e1["id"])
    assert item["entity"]["provenance"] in ("synthetic", "manual", "collected")
    assert item["status"] in ("analyzed", "partial", "unavailable")
    assert len(item["signals_summary"]) == 4
    assert item["detection_type"]  # plain-English label, never blank

    # filters
    assert f.client.get("/api/v1/detections", params={"entity_type": "social_profile"}, headers=h).json()["total"] == 1
    assert f.client.get("/api/v1/detections", params={"entity_type": "website"}, headers=h).json()["total"] == 1
    assert f.client.get("/api/v1/detections", params={"brand_id": str(uuid.uuid4())}, headers=h).json()["total"] == 0
    assert f.client.get("/api/v1/detections", params={"q": "acmebank_support"}, headers=h).json()["total"] == 1
    assert f.client.get("/api/v1/detections", params={"q": "no-such-asset-xyz"}, headers=h).json()["total"] == 0
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert f.client.get("/api/v1/detections", params={"from": future}, headers=h).json()["total"] == 0
    # status filter only accepts the three documented values
    for st in ("analyzed", "partial", "unavailable"):
        assert f.client.get("/api/v1/detections", params={"status": st}, headers=h).status_code == 200
    assert f.client.get("/api/v1/detections", params={"status": "low"}, headers=h).status_code == 422

    # sorting: risk_score desc puts the higher score first (nulls last)
    rs = f.client.get("/api/v1/detections", params={"sort": "risk_score", "order": "desc"}, headers=h).json()["items"]
    scores = [x["risk_score"] for x in rs if x["risk_score"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert f.client.get("/api/v1/detections", params={"sort": "bogus"}, headers=h).status_code == 422

    # detail endpoint returns the full assessment
    d = f.client.get(f"/api/v1/detections/{item['id']}", headers=h)
    assert d.status_code == 200, d.text
    assert d.json()["id"] == item["id"]
    assert len(d.json()["signals"]) == 4


def test_re_analyze_creates_new_assessment_and_keeps_history(world, f):
    e1, _ = _setup(f, world)
    h = world.h["inv"]
    aid = f.client.get("/api/v1/detections", params={"q": "acmebank_support"}, headers=h).json()["items"][0]["id"]
    before = f.client.get(f"/api/v1/entities/{e1['id']}/assessments", headers=h).json()["total"]
    r = f.client.post(f"/api/v1/detections/{aid}/re-analyze", headers=h)
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["id"] != aid  # a NEW assessment; the old one stays in history
    after = f.client.get(f"/api/v1/entities/{e1['id']}/assessments", headers=h).json()
    assert after["total"] == before + 1
    # the re-analyzed id is now the latest entry of the feed
    assert f.client.get("/api/v1/detections", params={"q": "acmebank_support"}, headers=h).json()["items"][0]["id"] == new["id"]


def test_re_analyze_is_permission_gated_and_404s_on_unknown(world, f):
    _setup(f, world)
    aid = f.client.get("/api/v1/detections", headers=world.h["inv"]).json()["items"][0]["id"]
    assert f.client.post(f"/api/v1/detections/{aid}/re-analyze", headers=world.h["partner"]).status_code == 403
    assert f.client.post(f"/api/v1/detections/{aid}/re-analyze", headers=world.h["outsider"]).status_code == 404
    assert f.client.post(f"/api/v1/detections/{uuid.uuid4()}/re-analyze", headers=world.h["inv"]).status_code == 404


def test_detections_scoped_to_own_organization(world, f):
    _setup(f, world)
    outsider_brand = f.brand(world.h["outsider_owner"], world.org_b, name="VictimCo", refs=False)
    out_ent = f.profile(world.h["outsider_owner"], outsider_brand["id"], handle="victimco_fakes")
    assert f.client.post(f"/api/v1/entities/{out_ent['id']}/analyze", headers=world.h["outsider"]).status_code == 201
    # outsider's own feed must not contain org A detections (and vice versa)
    inv_ids = {x["entity"]["id"] for x in f.client.get("/api/v1/detections", headers=world.h["inv"]).json()["items"]}
    out_ids = {x["entity"]["id"] for x in f.client.get("/api/v1/detections", headers=world.h["outsider"]).json()["items"]}
    assert out_ids and not (inv_ids & out_ids)
    # a raw UUID from the other org 404s
    some_id = f.client.get("/api/v1/detections", headers=world.h["outsider"]).json()["items"][0]["id"]
    assert f.client.get(f"/api/v1/detections/{some_id}", headers=world.h["inv"]).status_code == 404


def test_legacy_detection_endpoints_still_work(world, f):
    e1, _ = _setup(f, world)
    h = world.h["inv"]
    assert f.client.get("/api/v1/detection/signals", headers=h).status_code == 200
    sigs = f.client.get("/api/v1/detection/signals", params={"entity_id": e1["id"]}, headers=h).json()
    assert sigs["total"] == 4
    aid = sigs["items"][0]["assessment_id"]
    a = f.client.get(f"/api/v1/detection/assessments/{aid}", headers=h)
    assert a.status_code == 200 and a.json()["id"] == aid
    # bulk analyze by brand
    b = f.client.post("/api/v1/detection/analyze", json={"brand_id": str(world.brand["id"])}, headers=h)
    assert b.status_code == 200, b.text
    assert b.json()["analyzed"] == 2


def test_detections_purpose_filter_and_signals_entity_context(world, f):
    e1, e2 = _setup(f, world)
    h = world.h["inv"]
    # the Purpose filter is the entity's provenance: manual entities only, to begin with
    assert f.client.get("/api/v1/detections", params={"provenance": "manual"}, headers=h).json()["total"] == 2
    assert f.client.get("/api/v1/detections", params={"provenance": "synthetic"}, headers=h).json()["total"] == 0
    assert f.client.get("/api/v1/detections", params={"provenance": "bogus"}, headers=h).status_code == 422

    # a synthetic (sample) entity joins the feed under its own purpose
    syn = f.entity(h, world.brand["id"], "website", provenance="synthetic",
                   attributes={"url": "https://acmebank-demo-sample.top/claim"})
    assert f.client.post(f"/api/v1/entities/{syn['id']}/analyze", headers=h).status_code == 201
    page = f.client.get("/api/v1/detections", params={"provenance": "synthetic"}, headers=h).json()
    assert page["total"] == 1 and page["items"][0]["entity"]["id"] == syn["id"]
    assert page["items"][0]["entity"]["provenance"] == "synthetic"
    assert f.client.get("/api/v1/detections", params={"provenance": "manual"}, headers=h).json()["total"] == 2
    # the filter composes with brand scope (outsider org sees nothing of org A)
    assert f.client.get("/api/v1/detections", params={"provenance": "synthetic"}, headers=world.h["outsider"]).json()["total"] == 0

    # signals now carry their entity context; filters still behave with the join
    sigs = f.client.get("/api/v1/detection/signals", params={"entity_id": syn["id"]}, headers=h).json()
    assert sigs["total"] == 4 and all(s["entity"]["id"] == syn["id"] for s in sigs["items"])
    assert all(s["entity"]["display_name"] and s["entity"]["provenance"] == "synthetic" for s in sigs["items"])
    assert f.client.get("/api/v1/detection/signals", params={"signal_type": "nonsense"}, headers=h).status_code == 422
