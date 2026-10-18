"""Seed the demo database with a complete, self-consistent Nimbus dataset.

Run from ``backend/``:  ``python -m scripts.seed``   (uses DATABASE_URL from .env)

What it creates (all of it labelled synthetic - see the banner printed at the end):
  * 1 organization, 6 users (administrator password comes from BOOTSTRAP_ADMIN_PASSWORD)
  * 3 brands with official references (AcmeBank, NimbusAir, ShopLite) incl. official logo images
  * 40 entities (14 social profiles, 10 websites, 6 domains, 4 images, 6 mobile apps)
    - ~6 submitted as `manual`, the rest as `synthetic` (never conflated in the UI)
  * 1-4 historical assessments per entity (>= 80 total), each with the 4 detection signals,
    spread over the last 30 days. Every assessment is checked against the weighted model
    (|sum(w_i * s_i) - risk_score| < 0.01) before it is accepted.
  * ~60 relationships, including an explicit phishing cluster
  * 14 cases with the exact status distribution 2 detected / 2 triaged / 3 under_review /
    3 assigned / 2 escalated / 2 resolved, driven through the real workflow services
    (so events, notes, escalations and notifications are consistent)
  * 24 evidence records through the real evidence services (text/WHOIS/URL + uploaded screenshots)
  * monitoring targets for the mobile apps, and ~50 notifications

Idempotent: every table is TRUNCATEd (RESTART IDENTITY CASCADE) before seeding, so an old or
partially-seeded database is handled. No IntegrationConfig rows are created on purpose: the demo
shows connectors as "not configured" rather than pretending they are connected.
"""
from __future__ import annotations

import datetime as dt
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.models import (  # noqa: F401, E402
    Base, Brand, DigitalEntity, EntityRelationship, MonitoringTarget, Notification, Organization, User,
)
from app.models.enums import (  # noqa: E402
    EntityType, EvidenceKind, Provenance, ReferenceKind, RelationshipType, UserRole,
)
from app.services import analysis, audit, brands as brands_svc, cases as cases_svc, evidence as evidence_svc  # noqa: E402
from app.services import ingestion  # noqa: E402
from app.schemas.case import CaseCreate, EscalateRequest, ResolveRequest  # noqa: E402
from app.schemas.entity import EntitySubmit  # noqa: E402
from app.schemas.evidence import EvidenceCreate  # noqa: E402

random.seed(1337)

settings = get_settings()
SessionLocal = get_sessionmaker()

PASSWORD = "Demo-Passw0rd!"
ADMIN_PASSWORD = settings.bootstrap_admin_password
ORG_SLUG = "anarisk"
NOW = dt.datetime.now(dt.timezone.utc)

BRANDS = {
    "AcmeBank": {"domain": "acmebank.example", "handle": "acmebank", "package": "com.acmebank.mobile",
                 "publisher": "AcmeBank Ltd", "platform": "x",
                 "bio": "AcmeBank - secure everyday banking for everyone. Customer care is available 24/7 through the official app."},
    "NimbusAir": {"domain": "nimbusair.example", "handle": "nimbusair", "package": "com.nimbusair.fly",
                  "publisher": "NimbusAir SA", "platform": "instagram",
                  "bio": "NimbusAir - fly better. Official bookings and support through our app and website."},
    "ShopLite": {"domain": "shoplite.example", "handle": "shoplite", "package": "com.shoplite.shopping",
                 "publisher": "ShopLite GmbH", "platform": "x",
                 "bio": "ShopLite - everyday essentials delivered fast. Official store and customer support."},
}

# per-brand impersonation-flavoured seed material (all synthetic)
HANDLES = ["support", "helpdesk", "care", "official", "promo", "rewards", "updates", "service", "desk", "portal"]
SUFFIXES = ["", "24", "_hq", "_team", "_now", "_plus", "_direct", "_fast"]
TLDS = ["top", "xyz", "click", "support", "online"]
KEYWORDS = ["login", "verify", "secure", "update", "account", "bonus", "claim", "refund", "wallet", "kyc"]

SOCIAL_SPECS = [
    ("AcmeBank", "x", "acmebank_support_24", "Need help with your AcmeBank account? Message us your card number to verify."),
    ("AcmeBank", "x", "acmebank_care", "AcmeBank customer care - secure everyday banking for everyone."),
    ("AcmeBank", "x", "acme.bank.helpdesk", "Official helpdesk - reset your AcmeBank password here."),
    ("AcmeBank", "instagram", "acmebank_promos", "AcmeBank rewards - claim your bonus today."),
    ("AcmeBank", "x", "acmebank_updates", "Account update required - verify now to keep your AcmeBank account active."),
    ("AcmeBank", "x", "acmebank_refund", "AcmeBank refund desk - send your KYC to speed up processing."),
    ("AcmeBank", "instagram", "acmebank.offers", "Exclusive AcmeBank offers - airdrop for verified customers."),
    ("NimbusAir", "instagram", "nimbusair_help", "NimbusAir support - rebook your flight, send your booking reference."),
    ("NimbusAir", "x", "nimbusair_care", "NimbusAir customer care - fly better, we answer in minutes."),
    ("NimbusAir", "x", "nimbus.air.deals", "Cheap NimbusAir tickets - claim your giveaway now."),
    ("NimbusAir", "instagram", "nimbusair_promo", "NimbusAir promo - verify your account to unlock discounts."),
    ("ShopLite", "x", "shoplite_support", "ShopLite support - refund pending? Verify your account details."),
    ("ShopLite", "x", "shoplite_deals", "ShopLite bonus - claim daily rewards with one click."),
    ("ShopLite", "instagram", "shoplite.care", "ShopLite customer care - secure checkout help 24/7."),
]
WEBSITE_SPECS = [
    ("AcmeBank", "https://acmebank-secure-login.top/verify", "AcmeBank - Secure sign in"),
    ("AcmeBank", "https://acmebank-login.xyz/account", "Sign in to AcmeBank"),
    ("AcmeBank", "https://acmebank-verify.click/kyc", "AcmeBank KYC verification"),
    ("AcmeBank", "https://acme-bank.support/refund", "AcmeBank refund desk"),
    ("AcmeBank", "https://acmebankbonus.top/claim", "Claim your AcmeBank bonus"),
    ("NimbusAir", "https://nimbusair-rebook.top/flight", "NimbusAir - rebook now"),
    ("NimbusAir", "https://nimbus-air.support/tickets", "NimbusAir ticket support"),
    ("NimbusAir", "https://nimbusair-giveaway.xyz/claim", "NimbusAir giveaway"),
    ("ShopLite", "https://shoplite-refund.top/status", "ShopLite refund status"),
    ("ShopLite", "https://shop-lite.click/rewards", "ShopLite rewards"),
]
DOMAIN_SPECS = [
    ("AcmeBank", "acmebank-secure.top"),
    ("AcmeBank", "acmebank-help.xyz"),
    ("AcmeBank", "acmebank-verify.click"),
    ("NimbusAir", "nimbusair-booking.top"),
    ("NimbusAir", "nimbusair-support.xyz"),
    ("ShopLite", "shoplite-delivery.support"),
]
APP_SPECS = [
    ("AcmeBank", "AcmeBank Mobile", "com.acmebank.wallet", "Acme Bank Digital Ltd", "Verify your account at https://acmebank-secure-login.top/verify", ["READ_SMS", "INTERNET"]),
    ("AcmeBank", "AcmeBank Rewards", "com.acmebank.rewards", "Acme Rewards", "Claim your AcmeBank bonus: https://acmebankbonus.top/claim", ["INTERNET"]),
    ("NimbusAir", "NimbusAir Booking", "com.nimbusair.booking", "NimbusAir SA", "Rebook flights: https://nimbusair-rebook.top/flight", ["INTERNET", "ACCESS_FINE_LOCATION"]),
    ("NimbusAir", "NimbusAir Check-in", "com.nimbusair.checkin", "Nimbus Air Deals", "Check in online - verify your booking", ["INTERNET"]),
    ("ShopLite", "ShopLite Tracker", "com.shoplite.tracker", "ShopLite Deals", "Track your order: https://shoplite-refund.top/status", ["INTERNET", "READ_CONTACTS"]),
    ("ShopLite", "ShopLite Rewards", "com.shoplite.points", "ShopLite GmbH", "Daily rewards - claim now", ["INTERNET"]),
]


def _png(variant: int, official: bool = False) -> bytes:
    """Deterministic synthetic logo/screenshot bytes (unique per variant so uploads never collide)."""
    im = Image.new("RGB", (256, 256), "white")
    d = ImageDraw.Draw(im)
    if official:
        d.ellipse((30, 30, 226, 226), fill=(10, 40, 120))
        d.polygon([(80, 190), (128, 60), (176, 190), (150, 190), (128, 120), (106, 190)], fill="white")
        d.rectangle((100, 150, 156, 164), fill="white")
    else:
        base = (20 + 30 * variant) % 256
        d.rectangle((8, 8, 248, 60), fill=(base, 60, 140))
        for row in range(6):
            d.rectangle((16, 80 + row * 26, 240, 96 + row * 26), fill=(30, 30, 30 + row * 20))
        d.ellipse((180, 180, 240, 240), fill=(200, 40, 40))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _ago(days: float, hours: int = 0) -> dt.datetime:
    return NOW - dt.timedelta(days=days, hours=hours)


def main() -> None:
    t0 = time.time()
    db = SessionLocal()
    try:
        # ---- serialize concurrent seed runs (two seeds truncating each other
        #      mid-flight corrupt FK relationships) ---------------------------
        db.execute(text("SELECT pg_advisory_lock(77001337)"))

        # ---- idempotent reset: old/thin data is wiped wholesale -------------------
        tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
        db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.commit()
        print(f"truncated {len(Base.metadata.tables)} tables")

        # ---- organization + users -------------------------------------------------
        org = Organization(name="AnaRisk", slug=ORG_SLUG, description="Digital risk protection demo tenant (synthetic data)", is_active=True)
        db.add(org)
        db.flush()

        user_specs = [
            ("admin@nimbus.example", "Ada Admin", UserRole.ADMIN, ADMIN_PASSWORD),
            ("investigator@nimbus.example", "Ivo Investigator", UserRole.INVESTIGATOR, PASSWORD),
            ("investigator2@nimbus.example", "Ines Investigator", UserRole.INVESTIGATOR, PASSWORD),
            ("analyst@nimbus.example", "Nia Analyst", UserRole.INVESTIGATOR, PASSWORD),
            ("owner@nimbus.example", "Ola Owner", UserRole.BRAND_OWNER, PASSWORD),
            ("partner@nimbus.example", "Pia Partner", UserRole.PARTNER, PASSWORD),
        ]
        users: dict[str, User] = {}
        for email, name, role, pw in user_specs:
            u = User(email=email, full_name=name, role=role, organization_id=org.id,
                     hashed_password=hash_password(pw), is_active=True,
                     # Demo accounts are pre-verified: they have known passwords and no real
                     # inbox, so requiring email verification would lock them out of the demo.
                     email_verified_at=dt.datetime.now(dt.UTC))
            db.add(u)
            users[email.split("@")[0]] = u
        db.flush()
        admin, inv, inv2, analyst, owner = (users[k] for k in ("admin", "investigator", "investigator2", "analyst", "owner"))

        # ---- brands + official references (incl. official logo images) ------------
        brand_objs: dict[str, Brand] = {}
        for i, (name, spec) in enumerate(BRANDS.items()):
            b = Brand(organization_id=org.id, name=name, slug=name.lower(), is_active=True, is_synthetic=True,
                      description=f"Official {name} brand (synthetic demo tenant).")
            db.add(b)
            db.flush()
            brand_objs[name] = b
            for kind, value, platform in [
                (ReferenceKind.NAME, name, None),
                (ReferenceKind.DOMAIN, spec["domain"], None),
                (ReferenceKind.HANDLE, spec["handle"], spec["platform"]),
                (ReferenceKind.APP_PACKAGE, spec["package"], None),
                (ReferenceKind.PUBLISHER, spec["publisher"], None),
                (ReferenceKind.BIO, spec["bio"], None),
            ]:
                db.add(BrandReferenceRow(b.id, kind, value, platform))
            brands_svc.add_image_reference(db, owner, b.id, _png(i, official=True), note=f"official {name} logo", provenance=Provenance.MANUAL)
            db.flush()
        db.commit()

        # ---- entities --------------------------------------------------------------
        submits: list[EntitySubmit] = []
        for brand, platform, handle, bio in SOCIAL_SPECS:
            created = _ago(random.uniform(0, 30))
            submits.append(EntitySubmit(
                brand_id=brand_objs[brand].id, entity_type=EntityType.SOCIAL_PROFILE, platform=platform,
                provenance=Provenance.SYNTHETIC, analyze=False,
                attributes={"handle": handle, "bio": bio, "followers_count": random.randint(40, 9000),
                            "following_count": random.randint(10, 400),
                            "account_created_at": created.isoformat(),
                            "post_timestamps": [(created + dt.timedelta(days=k)).isoformat() for k in range(1, 12)],
                            "image_phashes": [f"{random.getrandbits(64):016x}"]},
                source_url=f"https://{platform}.example/@{handle}"))
        for brand, url, title in WEBSITE_SPECS:
            created = _ago(random.uniform(1, 30))
            submits.append(EntitySubmit(
                brand_id=brand_objs[brand].id, entity_type=EntityType.WEBSITE, provenance=Provenance.SYNTHETIC, analyze=False,
                attributes={"url": url, "page_title": title, "registered_at": created.isoformat()},
                source_url=url))
        for brand, domain in DOMAIN_SPECS:
            created = _ago(random.uniform(2, 30))
            submits.append(EntitySubmit(
                brand_id=brand_objs[brand].id, entity_type=EntityType.DOMAIN, provenance=Provenance.SYNTHETIC, analyze=False,
                attributes={"domain": domain, "registered_at": created.isoformat()}))
        for i, brand in enumerate(["AcmeBank", "NimbusAir", "ShopLite", "AcmeBank"]):
            submits.append(EntitySubmit(
                brand_id=brand_objs[brand].id, entity_type=EntityType.IMAGE, provenance=Provenance.SYNTHETIC, analyze=False,
                display_name=f"{brand} leaked promo image #{i + 1}",
                attributes={"phash": f"{random.getrandbits(64):016x}", "source_note": "scraped from a public post (synthetic)"}))
        for brand, app_name, package, publisher, description, permissions in APP_SPECS:
            created = _ago(random.uniform(1, 25))
            submits.append(EntitySubmit(
                brand_id=brand_objs[brand].id, entity_type=EntityType.MOBILE_APP, provenance=Provenance.SYNTHETIC, analyze=False,
                display_name=f"{app_name} (unofficial)", source_url=f"https://play.example/store/apps/details?id={package}",
                attributes={"app_name": app_name, "package_id": package, "store": "google_play", "publisher_name": publisher,
                            "store_url": f"https://play.example/store/apps/details?id={package}", "description": description,
                            "permissions": permissions, "permissions_source": "store_listing",
                            "linked_websites": [], "published_at": created.isoformat()}))

        # ~6 of the 40 are submitted as `manual` (unverified human input) - never relabelled as collected
        manual_idx = {0, 3, 8, 15, 22, 33}
        entities: list[DigitalEntity] = []
        for i, sub in enumerate(submits):
            if i in manual_idx:
                sub.provenance = Provenance.MANUAL
            entity, created_flag, _official = ingestion.submit_entity(db, admin, sub)
            seen = _ago(random.uniform(0, 30))
            entity.first_seen_at = seen
            entity.last_seen_at = seen + dt.timedelta(hours=random.randint(1, 72))
            entities.append(entity)
            if (i + 1) % 10 == 0:
                db.commit()
        db.commit()
        print(f"entities: {len(entities)} ({sum(1 for e in entities if e.provenance == Provenance.MANUAL)} manual, "
              f"{sum(1 for e in entities if e.provenance == Provenance.SYNTHETIC)} synthetic)")

        # ---- evidence (24, via the real evidence services) -------------------------
        by_brand: dict[str, list[DigitalEntity]] = {}
        for e in entities:
            by_brand.setdefault(e.brand.name, []).append(e)
        ev_count = 0
        for i in range(24):
            brand = list(BRANDS)[i % 3]
            entity = by_brand[brand][i % len(by_brand[brand])]
            if i % 3 == 0:  # uploaded screenshot
                evidence_svc.upload_image_evidence(db, inv, entity.id, _png(i), title=f"Screenshot of the {entity.display_name} profile",
                                                   description="Captured page screenshot (synthetic)", kind=EvidenceKind.SCREENSHOT,
                                                   provenance=Provenance.MANUAL, original_filename=f"screenshot-{i}.png")
            else:
                kind = (EvidenceKind.WHOIS, EvidenceKind.URL, EvidenceKind.TEXT)[i % 3]
                evidence_svc.create_evidence(db, inv, EvidenceCreate(
                    entity_id=entity.id, kind=kind, title=f"{kind.value} record #{i + 1}",
                    description=f"Collected {kind.value} material for {entity.display_name} (synthetic)",
                    source_url=entity.source_url, text_content=f"[synthetic] registrar/record details for {entity.canonical_id}",
                    provenance=Provenance.SYNTHETIC, metadata={"registrar": "Example Registrar", "observed": True}))
            ev_count += 1
        print(f"evidence: {ev_count}")

        # ---- assessments (1-4 per entity, 30-day spread) ----------------------------
        assessments = 0
        for i, e in enumerate(entities):
            runs = 1 + (i % 4)
            for r in range(runs):
                a = analysis.analyze_entity(db, admin, e, now=_ago(random.uniform(0, 30)), commit=False)
                eff, comp = a.effective_weights, a.component_scores
                if a.risk_score is not None:
                    calc = sum(eff[t] * comp[t] for t in eff if comp.get(t) is not None)
                    assert abs(calc - a.risk_score) < 0.01, f"weighted model mismatch for {e.canonical_id}: {calc} vs {a.risk_score}"
                assessments += 1
            if (i + 1) % 8 == 0:
                db.commit()
        db.commit()
        print(f"assessments: {assessments} (weighted-model assertion passed for all)")

        # ---- relationships (~60 incl. an explicit phishing cluster) -----------------
        rel_count = 0
        cluster = by_brand["AcmeBank"][:7]  # phishing cluster: the first AcmeBank impersonators
        cluster_edges = [(RelationshipType.SIMILAR_IDENTITY, 0.92), (RelationshipType.SHARES_DOMAIN, 0.88),
                         (RelationshipType.COORDINATED_BEHAVIOR, 0.81), (RelationshipType.SAME_INFRASTRUCTURE, 0.77),
                         (RelationshipType.SHARES_IMAGE, 0.7)]
        for i, a in enumerate(cluster):
            for j in range(i + 1, len(cluster)):
                kind, conf = cluster_edges[(i + j) % len(cluster_edges)]
                _rel(db, a.id, cluster[j].id, kind, conf,
                     f"Same phishing kit reuses this asset across {len(cluster)} AcmeBank impersonators (synthetic)")
                rel_count += 1
        target_rels = 60
        attempts = 0
        while rel_count < target_rels and attempts < 500:
            attempts += 1
            a, b = random.sample(entities, 2)
            if a.brand_id != b.brand_id:
                continue
            kind = random.choice(list(RelationshipType))
            _, was_new = _rel(db, a.id, b.id, kind, round(random.uniform(0.45, 0.95), 2),
                              f"Shared {kind.value.replace('_', ' ')} observed between the two assets (synthetic)", auto=True)
            if was_new:
                rel_count += 1
        db.commit()
        print(f"relationships: {rel_count}")

        # ---- cases (14, exact status distribution) ----------------------------------
        plan = (["detected"] * 2) + (["triaged"] * 2) + (["under_review"] * 3) + (["assigned"] * 3) + (["escalated"] * 2) + (["resolved"] * 2)
        case_ids: list[uuid.UUID] = []
        for i, target in enumerate(plan):
            brand = list(BRANDS)[i % 3]
            pool = by_brand[brand]
            entity_ids = [pool[(i + k) % len(pool)].id for k in range(1 + i % 3)]
            case, _ = cases_svc.create_case(db, inv, CaseCreate(
                brand_id=brand_objs[brand].id, title=f"{brand} impersonation cluster #{i + 1}",
                summary=f"Synthetic demo case covering {len(entity_ids)} linked {brand} impersonators.", entity_ids=entity_ids))
            if target in ("triaged", "under_review", "assigned", "escalated", "resolved"):
                cases_svc.change_status(db, inv, case.id, _st("triaged", comment="Triaged by the demo seed"))
            if target in ("under_review", "assigned", "escalated"):
                cases_svc.change_status(db, inv, case.id, _st("under_review", comment="Opened for review"))
            if target in ("assigned", "escalated"):
                cases_svc.assign(db, inv, case.id, inv2.id, note="Owned by the second investigator")
            if target == "escalated":
                cases_svc.escalate(db, inv, case.id, EscalateRequest(
                    partner_type="legal", partner_contact="legal@partner.example",
                    reason="Repeated brand impersonation and credential harvesting (synthetic handoff)",
                    requested_action="Takedown review"))
            if target == "resolved":
                cases_svc.resolve(db, inv, case.id, ResolveRequest(
                    outcome="confirmed_threat_actioned",
                    summary="Confirmed impersonation; synthetic takedown recorded and monitoring continues."))
            case_ids.append(case.id)
        print(f"cases: {len(case_ids)}")

        # ---- monitoring targets -----------------------------------------------------
        for e in [x for x in entities if x.entity_type == EntityType.MOBILE_APP]:
            db.add(MonitoringTarget(brand_id=e.brand_id, kind="mobile_app", package_id=e.attributes["package_id"],
                                    store=e.attributes.get("store", "google_play"), store_url=e.attributes.get("store_url"),
                                    monitoring_status="active" if random.random() > 0.2 else "paused", entity_id=e.id,
                                    last_sync_at=_ago(random.uniform(0, 5)), created_by_id=admin.id))
        db.commit()

        # ---- notifications (~50 total) ----------------------------------------------
        wanted = 50
        have = db.query(Notification).count()
        i = 0
        while have < wanted and i < len(entities):
            e = entities[i]
            if e.current_severity.value in ("high", "critical"):
                audit.record(db, admin, "seed.notify", "entity", e.id, details={"synthetic": True})
                from app.services import notifications as notify_svc
                notify_svc.notify_high_risk(db, e, analysis.latest_assessment(db, e.id))
                have = db.query(Notification).count()
            i += 1
        j = 0
        while db.query(Notification).count() < wanted and j < len(entities):
            e = entities[j]
            for uid in (inv.id, inv2.id):
                if db.query(Notification).count() >= wanted:
                    break
                db.add(Notification(user_id=uid, type="system", title="Scheduled synthetic sweep",
                                   body=f"Sweep completed for {e.display_name} - no change (demo data).",
                                   link_url=f"/entities/{e.id}", resource_type="entity", resource_id=e.id,
                                   is_read=(j % 3 == 0)))
                db.flush()
            j += 1
        db.commit()
        print(f"notifications: {db.query(Notification).count()}")

        # ---- summary -----------------------------------------------------------------
        counts = {
            "organizations": db.query(Organization).count(), "users": db.query(User).count(),
            "brands": db.query(Brand).count(), "entities": db.query(DigitalEntity).count(),
            "assessments": db.scalar(text("SELECT count(*) FROM risk_assessments")),
            "relationships": db.query(EntityRelationship).count(), "cases": db.scalar(text("SELECT count(*) FROM investigation_cases")),
            "evidence": db.scalar(text("SELECT count(*) FROM evidence_records")), "notifications": db.query(Notification).count(),
            "monitoring_targets": db.query(MonitoringTarget).count(),
            "integration_configs": db.scalar(text("SELECT count(*) FROM integration_configs")),
        }
        status_dist = {r[0]: r[1] for r in db.execute(text("SELECT status, count(*) FROM investigation_cases GROUP BY status"))}
        prov_dist = {r[0]: r[1] for r in db.execute(text("SELECT provenance, count(*) FROM digital_entities GROUP BY provenance"))}
        type_dist = {r[0]: r[1] for r in db.execute(text("SELECT entity_type, count(*) FROM digital_entities GROUP BY entity_type"))}
        sev_dist = {r[0]: r[1] for r in db.execute(text("SELECT current_severity, count(*) FROM digital_entities GROUP BY current_severity"))}

        print("\n" + "=" * 68)
        print("  *** ALL DATA IS SYNTHETIC - generated for demonstration only ***")
        print("  Detection scores are heuristic and unvalidated; review before acting.")
        print("=" * 68)
        print(f"  organization     {counts['organizations']}   users {counts['users']}")
        print(f"  brands           {counts['brands']}")
        print(f"  entities         {counts['entities']}   {type_dist}")
        print(f"  provenance       {prov_dist}")
        print(f"  severity         {sev_dist}")
        print(f"  assessments      {counts['assessments']}")
        print(f"  relationships    {counts['relationships']}")
        print(f"  cases            {counts['cases']}   {status_dist}")
        print(f"  evidence         {counts['evidence']}")
        print(f"  notifications    {counts['notifications']}")
        print(f"  monitoring       {counts['monitoring_targets']}")
        print(f"  integrations     {counts['integration_configs']} configured (connectors intentionally left NOT configured)")
        print("\n  Demo accounts (passwords shown once, demo only):")
        print(f"    admin          admin@nimbus.example  {ADMIN_PASSWORD}")
        for email, _n, role, _p in user_specs[1:]:
            print(f"    {email.split('@')[0]:<14} {email}  {PASSWORD}")
        print(f"\n  Seeded in {time.time() - t0:.1f}s")
    finally:
        db.close()


def _st(status: str, **kw):
    from app.models.enums import CaseStatus
    from app.schemas.case import CaseStatusUpdate

    return CaseStatusUpdate(status=CaseStatus(status), **kw)


def _rel(db, a_id, b_id, kind, confidence, note, auto: bool = False):
    from app.services.graph import upsert_relationship

    return upsert_relationship(db, a_id, b_id, kind, confidence, note, None, auto=auto, actor=None, meta={})


class BrandReferenceRow:
    """Convenience builder so the reference rows keep their normalisation consistent with services/brands.py."""

    def __new__(cls, brand_id, kind, value, platform=None):
        from app.models import BrandReference
        from app.services.official import normalize_reference

        return BrandReference(brand_id=brand_id, kind=kind, value=value.strip(),
                              normalized_value=normalize_reference(kind, value), platform=platform,
                              provenance=Provenance.MANUAL)


if __name__ == "__main__":
    main()
