"""Pure unit tests of each detection family (no database)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings, get_settings
from app.models import Brand, BrandReference, DigitalEntity, EvidenceRecord
from app.models.enums import EntityType, Provenance, ReferenceKind, SignalStatus
from app.services.detection import DetectionContext
from app.services.detection.behavior import BehaviorDetector
from app.services.detection.brand_logo import BrandLogoDetector, distance_to_score
from app.services.detection.impersonation import ImpersonationDetector
from app.services.detection.url_risk import UrlRiskDetector

NOW = datetime(2026, 10, 11, tzinfo=UTC)
OFFICIAL_HASH = "f869a5169f611a69"


def flip(h: str, bits: int) -> str:
    return f"{int(h, 16) ^ ((1 << bits) - 1):016x}"


def ref(kind, value, **kw):
    from app.services.official import normalize_reference
    return BrandReference(id=uuid.uuid4(), kind=kind, value=value, normalized_value=normalize_reference(kind, value), **kw)


def default_refs():
    return [ref(ReferenceKind.NAME, "AcmeBank"), ref(ReferenceKind.DOMAIN, "acmebank.example"), ref(ReferenceKind.HANDLE, "acmebank", platform="x"),
            ref(ReferenceKind.PUBLISHER, "AcmeBank Ltd"), ref(ReferenceKind.IMAGE, OFFICIAL_HASH, perceptual_hash=OFFICIAL_HASH, note="official logo"),
            ref(ReferenceKind.BIO, "AcmeBank - secure everyday banking for everyone. Customer care is available 24/7 through the official app.")]


def entity(etype=EntityType.SOCIAL_PROFILE, name="Some Account", attrs=None, **kw):
    return DigitalEntity(id=uuid.uuid4(), brand_id=uuid.uuid4(), entity_type=etype, canonical_id=name.lower(), display_name=name, attributes=attrs or {},
                         provenance=Provenance.MANUAL, **kw)


def ctx(e, refs=None, evidence=(), peers=(), count=1):
    brand = Brand(id=e.brand_id, name="AcmeBank", organization_id=uuid.uuid4(), slug="acmebank")
    return DetectionContext(entity=e, brand=brand, references=default_refs() if refs is None else refs, evidence=list(evidence), peers=list(peers),
                            collection_count=count, settings=get_settings(), now=NOW)


# ---------------- A. brand and logo ----------------
def test_logo_distance_to_score_is_monotonic_and_bounded():
    s = [distance_to_score(d, 6, 14) for d in range(0, 20)]
    assert s[0] == 1.0 and s[-1] == 0.0 and all(a >= b for a, b in zip(s, s[1:])) and all(0 <= x <= 1 for x in s)


def test_logo_exact_near_far():
    exact = BrandLogoDetector().run(ctx(entity(attrs={"image_phashes": [OFFICIAL_HASH]})))
    near = BrandLogoDetector().run(ctx(entity(attrs={"image_phashes": [flip(OFFICIAL_HASH, 3)]})))
    far = BrandLogoDetector().run(ctx(entity(attrs={"image_phashes": [flip(OFFICIAL_HASH, 32)]})))
    assert exact.status == SignalStatus.OK and exact.score == 1.0 and "identical perceptual hash" in exact.explanation
    assert 0.6 < near.score < 1.0 and near.metadata["best_distance"] == 3 and "visually very similar" in near.explanation
    assert far.status == SignalStatus.OK and far.score == 0.0 and "No visual match" in far.explanation
    assert {"type": "brand_reference"} .items() <= exact.evidence_refs[0].items()
    assert exact.metadata["hash_bits"] == 64 and exact.metadata["compared_official_images"] == 1


def test_logo_uses_uploaded_evidence_and_cites_it():
    ev = EvidenceRecord(id=uuid.uuid4(), perceptual_hash=flip(OFFICIAL_HASH, 2), sha256="a" * 64)
    r = BrandLogoDetector().run(ctx(entity(), evidence=[ev]))
    assert r.score > 0.7 and {"type": "evidence", "id": str(ev.id)} in r.evidence_refs


def test_logo_byte_identical_file_match_by_sha256():
    sha = "b" * 64
    refs = [ref(ReferenceKind.IMAGE, "0000000000000001", perceptual_hash="0000000000000001", sha256=sha)]
    r = BrandLogoDetector().run(ctx(entity(attrs={"sha256": sha}, etype=EntityType.IMAGE), refs=refs))
    assert r.status == SignalStatus.OK and r.score == 1.0 and "byte-identical" in r.explanation


def test_logo_unavailable_not_zero():
    no_img = BrandLogoDetector().run(ctx(entity()))
    assert no_img.status == SignalStatus.UNAVAILABLE and no_img.score is None and "no image data" in no_img.explanation
    no_ref = BrandLogoDetector().run(ctx(entity(attrs={"image_phashes": [OFFICIAL_HASH]}), refs=[ref(ReferenceKind.NAME, "AcmeBank")]))
    assert no_ref.status == SignalStatus.UNAVAILABLE and "no registered official images" in no_ref.explanation


# ---------------- B. impersonation ----------------
@pytest.mark.parametrize("name", ["AcmeBank Support", "Acme_Bank_Official", "аcmebаnk", "AcmeBnak", "acme-bank-care"])
def test_impersonation_flags_lookalike_names(name):
    r = ImpersonationDetector().run(ctx(entity(name=name)))
    assert r.status == SignalStatus.OK and r.score >= 0.5, (name, r.score, r.explanation)
    assert "resembles official" in r.explanation


def test_impersonation_unrelated_is_low_but_available():
    r = ImpersonationDetector().run(ctx(entity(name="Gardening Tips Daily", attrs={"handle": "garden_tips", "bio": "We love roses and tomatoes and sharing seasonal advice with you."})))
    assert r.status == SignalStatus.OK and r.score == 0.0 and "No meaningful resemblance" in r.explanation


def test_impersonation_copied_bio_and_corroboration():
    bio = "AcmeBank - secure everyday banking for everyone. Customer care is available 24/7 - DM us!"
    only_bio = ImpersonationDetector().run(ctx(entity(name="Totally Different Name", attrs={"handle": "zzz_qqq", "bio": bio})))
    both = ImpersonationDetector().run(ctx(entity(name="AcmeBank Help", attrs={"bio": bio})))
    assert only_bio.score > 0.5 and "likely copied" in only_bio.explanation
    assert both.score > only_bio.score and "multiple independent identity fields agree" in both.explanation


def test_impersonation_publisher_and_package():
    e = entity(EntityType.MOBILE_APP, name="Rewards Plus", attrs={"app_name": "Rewards Plus", "publisher_name": "Acme Bank Ltd.", "package_id": "com.acmebank.rewards"})
    r = ImpersonationDetector().run(ctx(e, refs=default_refs() + [ref(ReferenceKind.APP_PACKAGE, "com.acmebank.mobile")]))
    assert r.score >= 0.6 and any(m["kind"] == "publisher" for m in r.metadata["matches"])


def test_impersonation_claims_official_boost_and_refs():
    plain = ImpersonationDetector().run(ctx(entity(name="AcmeBank Rewards")))
    claim = ImpersonationDetector().run(ctx(entity(name="AcmeBank Official Rewards")))
    assert claim.score >= plain.score and claim.metadata["claims_official"] is True
    handle_ref = [m for m in claim.metadata["matches"] if m.get("reference_id")]
    assert all(r["type"] == "brand_reference" for r in claim.evidence_refs)


def test_impersonation_flags_credential_and_payment_solicitation():
    ask = ImpersonationDetector().run(ctx(entity(name="AcmeBank Care", attrs={"bio": "Message us your card number to verify your account and send money for processing."})))
    assert ask.metadata["solicits_sensitive_action"] is True
    assert "card number" in ask.metadata["solicitation_phrases_matched"] and "send money" in ask.metadata["solicitation_phrases_matched"]
    assert "text asks for credentials or money" in ask.explanation


def test_impersonation_clean_text_is_not_flagged_as_solicitation():
    r = ImpersonationDetector().run(ctx(entity(name="Gardening Tips Daily", attrs={"bio": "We love roses and tomatoes and sharing seasonal advice with you."})))
    assert r.metadata["solicits_sensitive_action"] is False and r.metadata["solicitation_phrases_matched"] == []


def test_solicitation_matching_is_word_bounded():
    from app.services.detection.impersonation import solicitation_matches
    assert solicitation_matches("your hotpot recipe", ["otp"]) == []          # 'otp' must not match inside 'hotpot'
    assert solicitation_matches("reset your otp now", ["otp"]) == ["otp"]


# ---------------- C. URLs ----------------
def url_entity(*urls, **attrs):
    return entity(EntityType.SOCIAL_PROFILE, attrs={"links": list(urls), **attrs})


@pytest.mark.parametrize("url,code", [
    ("https://acmebank-secure-login.xyz/verify", "lookalike_domain"), ("https://acmebank.xyz", "lookalike_domain"), ("https://acrnebank.example/x", "lookalike_domain"),
    ("http://xn--acmbank-9ya.com", "punycode"), ("http://192.0.2.10/login", "ip_host"), ("https://acmebank.example@evil-site.com/", "userinfo"),
    ("https://bit.ly/3abcd", "shortener"), ("https://login.verify.account.update.secure-pay.top/x", "many_subdomains"),
])
def test_url_indicators_fire(url, code):
    r = UrlRiskDetector().run(ctx(url_entity(url)))
    codes = {i["code"] for res in r.metadata["results"] for i in res["indicators"]}
    assert r.status == SignalStatus.OK and code in codes, (url, codes)


def test_url_official_domain_is_zero_and_explained():
    r = UrlRiskDetector().run(ctx(url_entity("https://www.acmebank.example/help", "https://login.acmebank.example")))
    assert r.status == SignalStatus.OK and r.score == 0.0 and "official brand domains" in r.explanation


def test_url_homoglyph_domain_detected_via_unicode_form():
    r = UrlRiskDetector().run(ctx(url_entity("https://аcmebаnk.com/login")))   # cyrillic a's
    assert r.score >= 0.7 and any(i["code"] == "lookalike_domain" for i in r.metadata["results"][0]["indicators"])


def test_url_score_is_highest_across_urls_and_bounded():
    r = UrlRiskDetector().run(ctx(url_entity("https://www.acmebank.example", "https://acmebank-verify-login.top/verify?account=1")))
    assert 0.6 < r.score <= 1.0 and r.metadata["urls_analyzed"] == 2


def test_url_unavailable_without_urls_and_ignores_garbage():
    assert UrlRiskDetector().run(ctx(entity())).status == SignalStatus.UNAVAILABLE
    r = UrlRiskDetector().run(ctx(entity(attrs={"description": "no links here"})))
    assert r.status == SignalStatus.UNAVAILABLE
    r = UrlRiskDetector().run(ctx(entity(attrs={"links": ["javascript:alert(1)", "file:///etc/passwd"]})))
    assert r.status == SignalStatus.UNAVAILABLE and "unparseable" in r.explanation


def test_url_extracts_links_from_bio_and_website_entities():
    r = UrlRiskDetector().run(ctx(entity(attrs={"bio": "claim now at www.acmebank-bonus.top/claim today"})))
    assert r.status == SignalStatus.OK and r.score > 0.5
    site = entity(EntityType.WEBSITE, name="site", attrs={"url": "https://acmebank-bonus.top/claim"}, source_url="https://acmebank-bonus.top/claim")
    assert UrlRiskDetector().run(ctx(site)).score > 0.5


def test_url_store_listing_itself_is_not_scored():
    app = entity(EntityType.MOBILE_APP, name="app", attrs={"store_url": "https://play.google.com/store/apps/details?id=x.y", "app_name": "app"}, source_url="https://play.google.com/store/apps/details?id=x.y")
    assert UrlRiskDetector().run(ctx(app)).status == SignalStatus.UNAVAILABLE


# ---------------- D. behaviour ----------------
def ts(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def test_behavior_new_account_and_age_buckets():
    new = BehaviorDetector().run(ctx(entity(attrs={"account_created_at": (NOW - timedelta(days=3)).isoformat()})))
    old = BehaviorDetector().run(ctx(entity(attrs={"account_created_at": (NOW - timedelta(days=2000)).isoformat()})))
    assert new.score == 1.0 and old.score == 0.0
    assert new.metadata["components"]["velocity"]["available"] is False       # unavailable, not zero
    assert "Not assessed (no data): velocity, coordination" in new.explanation
    assert BehaviorDetector().run(ctx(entity(attrs={"account_created_at": (NOW - timedelta(days=45)).isoformat()}))).score == 0.4


def test_behavior_velocity_from_posts_and_follower_growth():
    posts = [ts(i) for i in range(1, 61)]                                     # 60 posts in an hour
    r = BehaviorDetector().run(ctx(entity(attrs={"post_timestamps": posts})))
    assert r.metadata["components"]["velocity"]["posts_per_day"] > 1000 and r.score == 1.0
    few = BehaviorDetector().run(ctx(entity(attrs={"post_timestamps": posts[:3]})))
    assert few.status == SignalStatus.UNAVAILABLE                              # too few timestamps -> not invented
    growth = BehaviorDetector().run(ctx(entity(attrs={"account_created_at": (NOW - timedelta(days=2)).isoformat(), "followers_count": 40000})))
    assert growth.metadata["components"]["velocity"]["score"] == 1.0


def test_behavior_coordination_with_peers_and_unavailable_without():
    shared = {"image_phashes": [OFFICIAL_HASH], "links": ["https://evil-campaign.top/a"], "bio": "Win big rewards with our amazing exclusive community offers every day"}
    a, b = entity(name="Alpha One", attrs=shared), entity(name="Beta Two", attrs=dict(shared))
    r = BehaviorDetector().run(ctx(a, peers=[b]))
    co = r.metadata["components"]["coordination"]
    assert co["available"] and co["score"] > 0.7 and {"shares_image", "shares_domain", "similar_identity"} <= set(co["shared_indicators"])
    assert {"type": "entity", "id": str(b.id)} in r.evidence_refs
    alone = BehaviorDetector().run(ctx(a, peers=[]))
    assert alone.status == SignalStatus.UNAVAILABLE and alone.metadata["components"]["coordination"]["available"] is False


def test_behavior_no_overlap_with_peer_is_available_but_zero():
    a = entity(name="Alpha One", attrs={"image_phashes": [OFFICIAL_HASH]})
    b = entity(name="Zzz Unrelated", attrs={"image_phashes": [flip(OFFICIAL_HASH, 40)]})
    r = BehaviorDetector().run(ctx(a, peers=[b]))
    assert r.status == SignalStatus.OK and r.score == 0.0


def test_behavior_synchronised_posting_detected():
    base = [NOW - timedelta(hours=i) for i in range(1, 8)]
    a = entity(name="Poster A", attrs={"post_timestamps": [t.isoformat() for t in base]})
    b = entity(name="Poster B", attrs={"post_timestamps": [(t + timedelta(seconds=20)).isoformat() for t in base]})
    r = BehaviorDetector().run(ctx(a, peers=[b]))
    assert "coordinated_behavior" in r.metadata["components"]["coordination"]["shared_indicators"]


def test_behavior_partial_availability_renormalises():
    r = BehaviorDetector().run(ctx(entity(attrs={"account_created_at": (NOW - timedelta(days=20)).isoformat()}), count=1))
    assert r.score == 0.7                                                       # only age available -> its own score, not diluted by zeros


def test_behavior_repeated_submissions_contribute_to_coordination_only_with_peers():
    a = entity(name="Alpha One", attrs={"image_phashes": [OFFICIAL_HASH]})
    b = entity(name="Zzz Unrelated", attrs={"image_phashes": [flip(OFFICIAL_HASH, 40)]})
    r = BehaviorDetector().run(ctx(a, peers=[b], count=5))
    assert r.metadata["components"]["coordination"]["repeated_submissions"] == 5
