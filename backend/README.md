# Nimbus Ninjas — Digital Risk Protection Platform (backend)

This directory is a standalone FastAPI project. Its migrations, Docker setup, tests,
environment template, and application code are self-contained here.

FastAPI + PostgreSQL backend implementing the four-layer design from the project documentation:

**Digital Surface Collection → Detection Engine → Risk Graph → Explainable Case Review → Response & Resolution**

Fake/impersonating profiles, lookalike websites/domains and suspicious mobile apps are ingested through one pipeline,
scored by four independent explainable signal families, linked in a risk graph, and worked as cases with a validated
workflow, ownership, partner handoffs and an audit trail.

> **Read this first — what is and is not real**
> * **No live monitoring exists.** No platform/app-store connector is configured (that needs credentials and data-sharing
>   agreements). `GET /api/v1/collection/connectors` reports `live: false`. Data enters by **manual submission** or the
>   **synthetic sample connector**. Every record carries `provenance` = `collected | manual | synthetic`; the platform
>   never presents manual or synthetic input as observed fact, and `collected` is reserved for real connectors.
> * **Scoring is heuristic and unvalidated.** Weights, thresholds and rules are illustrative and need validation against
>   labelled data. Risk scores need human review; **nothing is closed, escalated or taken down automatically**, and
>   escalation only *records* a handoff — it contacts no one.
> * Mobile-app `permissions` / `publisher` are shown as **supplied-unverified** unless collected from a store listing;
>   `publisher_verified` is always `false`.
> * All seed data is **synthetic** (the demo brand "AcmeBank" is fictional).

## Quick start

### A) Docker (PostgreSQL + API, migrations applied automatically)
```bash
cp .env.example .env            # optional; compose has working development defaults
docker compose up --build       # API on http://localhost:8000, Postgres on :5432
docker compose run --rm api python -m scripts.seed      # synthetic demo data (refuses to run if ENVIRONMENT=production)
```
### B) Local (Python 3.12+, PostgreSQL 14+)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # defaults match: user nimbus / password nimbus_dev_pw / dbs nimbus + nimbus_test
# create the databases once (or use `docker compose up db`):
#   CREATE USER nimbus WITH PASSWORD 'nimbus_dev_pw' CREATEDB;  CREATE DATABASE nimbus OWNER nimbus;  CREATE DATABASE nimbus_test OWNER nimbus;
alembic upgrade head            # schema comes from migrations, never create_all
python -m scripts.seed          # optional synthetic demo data
uvicorn app.main:app --reload   # http://localhost:8000
```
* **API docs:** http://localhost:8000/docs (Swagger — click *Authorize*) · http://localhost:8000/redoc · `/openapi.json`
* **Health:** `GET /api/v1/health` (liveness) · `GET /api/v1/ready` (DB reachable **and** migrations at head; 503 otherwise)

### Demo accounts (created by the seed script — development only)
| Email | Role | Password |
|---|---|---|
| `admin@nimbus.example` | administrator | `BOOTSTRAP_ADMIN_PASSWORD` (default `ChangeMe-Admin-123`) |
| `investigator@nimbus.example`, `investigator2@nimbus.example`, `analyst@nimbus.example` | investigator | `Demo-Passw0rd!` |
| `owner@nimbus.example` | brand_owner | `Demo-Passw0rd!` |
| `partner@nimbus.example` | partner | `Demo-Passw0rd!` |

Cross-organization isolation is covered by the test suite (an outsider's investigator in a second organization gets
404s for every resource of the first).

The seed builds a synthetic brand with official references (incl. a generated logo), lookalike profiles/sites/apps with
evidence images and text, discovered graph relationships, risk assessments, cases across the workflow (incl. one
escalated partner handoff), notifications, monitored app-store packages and a *not_configured* integration catalog,
following the 3-minute demo flow in the documentation. It is idempotent: re-running it truncates and rebuilds the demo
data. **All integration credentials are intentionally left unconfigured** — connect them from the UI to see them work.

## Tests
```bash
pytest                      # 286 tests, ~3 min; uses TEST_DATABASE_URL (database name MUST end in "_test")
```
The suite builds its schema with the real Alembic migrations, truncates tables between tests, uploads to a temp dir and
refuses to run against a database whose name does not end in `_test`. It covers auth/JWT (incl. forgot/reset/change
password flows), RBAC, tenant isolation, ingestion/dedup, every detector, scoring/confidence, evidence upload validation
(inc. hash verification and case linking), SSRF defences (incl. a real-socket test), graph/clustering, the case workflow
(inc. a concurrent-request race, PATCH optimistic concurrency and admin-only delete), dashboard aggregation, audit,
notifications, integrations (encryption at rest, honest test/sync), app monitoring, reports + CSV exports, the detections
feed, migrations (round-trip + model/migration drift check) and error handling.

## Architecture
```
app/
  main.py                    app factory, CORS, security headers, health/ready
  core/    config.py permissions.py security.py errors.py rate_limit.py context.py
  api/     deps.py  v1/{auth,users,brands,collection,entities,evidence,detection,graph,cases,dashboard,audit,
                        notifications,integrations,monitoring,reports}.py   (thin handlers)
  services/                  business logic: ingestion, analysis, scoring, graph, cases, dashboard, audit, notifications,
                             case_notify, url_inspector, crypto_utils, evidence, monitoring, reports, connectors/
    detection/               brand_logo.py impersonation.py url_risk.py behavior.py  + common.py (shared evidence helpers)
  repositories/              access.py (org/brand scoping)  entities.py (filtered queries)
  models/ schemas/ db/ utils/ (text, urls, images)
alembic/versions/20261011_0001_initial_schema.py  20261013_0002_notifications_integrations_monitoring.py     scripts/seed.py     tests/
```
Detectors implement one tiny protocol (`run(ctx) -> SignalResult`) and are registered in `services/detection/__init__.py`;
connectors implement `SourceConnector` (`services/connectors/base.py`) — both are swappable without touching routes.

### Data model (23 tables)
`organizations, users` (incl. JSONB `preferences`) · `brands, brand_references` (official name/handle/domain/app package/publisher/bio/image+pHash) ·
`data_sources, collection_records` (one row per ingestion event, raw payload kept) · `digital_entities` (social profile,
website, domain, image, mobile app; unique per brand+type+canonical id) · `evidence_records` (entity link optional — evidence
can outlive an unlink; SHA-256 + perceptual hash + verification status) · `risk_assessments`
(**immutable history**: model version, configured + effective weights, component scores, risk, confidence + breakdown,
thresholds) · `detection_signals` (per assessment: type, status, score, explanation, evidence refs, metadata) ·
`entity_relationships` (undirected edge: type, confidence, evidence ref/note, timestamps; CHECK constraints for canonical
order / no self-loops / ranges) · `investigation_cases, case_entities, case_assignments` (history; partial unique index = one
open owner), `case_notes, case_events` (append-only status history), `case_escalations` (partner handoffs),
`case_evidence` (explicit evidence↔case links with role) · `notifications` (in-app, per user) · `password_reset_tokens`
(SHA-256 hashed, single-use, 30-minute expiry) · `integration_configs` (per-organization provider settings, encrypted at
rest with Fernet) · `monitoring_targets` (store packages watched per brand) · `audit_logs`.

## Detection engine (explainable, four independent families)
Each signal returns: type, **score ∈ [0,1] or null**, `status` (`ok | unavailable | failed`), evidence refs, a human-readable
explanation and metadata. **Missing input ⇒ `unavailable`, never zero risk.**

| Signal | What it uses |
|---|---|
| `brand_logo` | 64-bit pHash (Pillow + ImageHash) of entity images/uploaded evidence vs registered official images; exact-file match by SHA-256. Score: exact 1.0 → near-duplicate (≤6 bits) 0.95…0.60 → 0 at ≥14 bits |
| `impersonation` | RapidFuzz + normalisation (accents, homoglyphs, leetspeak, generic words like "official/support" ignored anywhere) over names, handles, app names, package ids, **publisher** and **bios** vs official references |
| `url_risk` | safe-parsed URLs: lookalike/typosquat/homoglyph domains vs official domains, brand-in-host, punycode, IP hosts, `@` userinfo, shorteners, risky TLDs, subdomain depth, request keywords (all configurable); official domains score 0 |
| `behavior` | account age, post velocity & follower growth, and **coordination** with other entities of the brand (shared image/domain/identity/infrastructure/synchronised posting); each sub-component is independently available/unavailable |

**Risk** `R = Σ wᵢsᵢ / Σ wᵢ` over *available* signals (weights 0.30/0.30/0.25/0.15, normalised to 1; with all four available
this is exactly `w1s1+w2s2+w3s3+w4s4`). **Severity** thresholds: ≥0.40 medium, ≥0.60 high, ≥0.80 critical (configurable).
**Confidence** is separate: `0.4·evidence_quality + 0.3·availability + 0.3·corroboration` where evidence quality depends on
cited evidence and **provenance** (collected 1.0 / manual 0.6 / synthetic 0.3), availability is the weight coverage,
corroboration = `((n_ok−1)/3)·(1−spread)`. **Synthetic entities are capped at 0.40 confidence.** If no signal is available
the result is `risk=null, severity=unknown` (not "low"). `GET /api/v1/detection/model` returns the live configuration.

## Risk graph & campaigns
NetworkX `MultiGraph` rebuilt from persisted `entity_relationships` on each request (so "rebuild" is always available; every relationship
is its own edge with type, confidence, evidence reference and timestamp). Edge types: `shares_image, shares_domain,
similar_identity, same_infrastructure, coordinated_behavior`. `POST /graph/discover` derives edges from observable data;
investigators can also assert edges. Filters: brand, entity type, min risk, severity, min edge confidence; neighbors,
related-entity ranking (strongest path), clusters with summaries. **A connected component is not automatically malicious:**
a cluster is *proposed* only if size, mean link confidence and highest member risk pass configurable thresholds and no open case
already covers it (reasons are returned either way). Opening a case from a cluster is always a human action.

## Case workflow
`DETECTED → TRIAGED → UNDER_REVIEW → ASSIGNED → ESCALATED → RESOLVED` (configurable via `CASE_TRANSITIONS` defaults in `core/config.py`).
Documented shortcuts: `TRIAGED/UNDER_REVIEW/ASSIGNED → RESOLVED` (needs outcome + summary). Backward: `UNDER_REVIEW→TRIAGED`,
`ASSIGNED→UNDER_REVIEW`, `ESCALATED→ASSIGNED`. Reopen `RESOLVED→UNDER_REVIEW`: administrators only, comment required.
`ASSIGNED` requires an owner (use `/assign`, which also auto-advances `UNDER_REVIEW→ASSIGNED`); `ESCALATED` requires handoff
details (use `/escalate`). Safety: row locking, optional `expected_status` (409 on stale/duplicate requests), `Idempotency-Key`
header on case creation, idempotent re-assignment. Every transition writes a `case_events` row and an `audit_logs` row.

## Security
* bcrypt over a SHA-256 prehash (no 72-byte truncation); JWT (HS256) with `exp/iat/jti`; secret from env — **the app refuses to start
  in production with the placeholder/short secret, `*` CORS or `DEBUG=true`**; deactivated users lose access immediately;
  login errors are indistinguishable (bad password / unknown / disabled) with timing equalisation; login/registration rate limits.
* **Public registration** creates a `brand_owner` with *no organization* (zero data access) — callers can never pick role/org. Disable with `ALLOW_PUBLIC_REGISTRATION=false`.
* RBAC (`core/permissions.py`) + organization scoping on every query; cross-tenant resources return **404**. Partners see only escalated cases.
* **SSRF:** `url_inspector.py` — disabled by default (`URL_FETCH_ENABLED=false`); http/https only, ports 80/443, no userinfo, DNS resolved by us,
  *all* answers must be public (loopback/private/link-local/CGNAT/reserved/IPv4-mapped/NAT64/6to4 blocked), connection pinned to the validated IP,
  manual redirects re-validated per hop (max 3), timeouts, size cap, no body storage/execution, optional domain allowlist.
* Uploads: PNG/JPEG/WEBP/GIF only, validated by decoding the bytes (extension/MIME ignored), size + pixel-count limits (decompression bombs),
  stored under the content SHA-256 (client filename never used), served with `nosniff` + restrictive CSP. SVG is rejected.
* Parameterised SQL via SQLAlchemy, error bodies never leak internals, secrets/tokens/passwords are scrubbed from audit details.

## Configuration
See `.env.example` (all weights, thresholds and limits are in `app/core/config.py` and overridable by environment variables).
Production guidance: set `ENVIRONMENT=production`, a random `SECRET_KEY` (≥32 chars), explicit `CORS_ORIGINS`, a managed PostgreSQL with
a non-default password and no published port, run behind TLS (`--proxy-headers` is on), keep `URL_FETCH_ENABLED=false` unless the host has an
egress firewall, store `UPLOAD_DIR` on a persistent volume (or swap for object storage), run `alembic upgrade head` as a deploy step,
and note the in-memory rate limiter is **per process** — use a gateway/Redis if you run several workers.

## Adding a live data source
Subclass `SourceConnector` (`services/connectors/base.py`), set `kind=SourceKind.CONNECTOR`, `live=True`, implement `is_configured()` (credentials) and
`collect()` (return `NormalizedEntity` items from sources you are *authorized* to read), then `register()` it. Output is stored with `provenance=collected`.
Unconfigured connectors answer `409 connector_not_configured`.

## Frontend integration
No frontend existed in the repository, so no existing contract was adapted. The API is JSON, paginated as `{items,total,page,page_size,pages}`,
errors are `{"error":{"code","message","details"}}`, auth is `Authorization: Bearer <token>`. Dashboard screens map to:
`/dashboard/stats` (totals, distributions, recent detections, top risk, latest activity), `/dashboard/mobile-apps`, `/graph` + `/graph/clusters`,
`/cases` + `/cases/{id}` (evidence, signals, linked entities, notes, history, `allowed_transitions`), `/entities/{id}` (latest explainable assessment).

## API reference

**Audit**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/audit` | Audit history (administrators: all; others: own organization only) |

**Authentication**

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/login` | Login with JSON credentials |
| GET | `/api/v1/auth/me` | Current user (incl. `preferences` and `organization` summary) |
| PATCH | `/api/v1/auth/me` | Update your own profile (full name, email → 409 if taken, preferences) |
| POST | `/api/v1/auth/register` | Self-register (brand_owner role, no organization until an administrator assigns one) |
| POST | `/api/v1/auth/token` | OAuth2 password form (used by Swagger 'Authorize') |
| POST | `/api/v1/auth/forgot-password` | Always 200 (no user enumeration). Known address → single-use 30-minute token (SHA-256 stored); non-production also returns `dev_reset_token` |
| POST | `/api/v1/auth/reset-password` | Set a new password with a valid token (400 `invalid_or_expired_token` otherwise); invalidates other outstanding tokens |
| POST | `/api/v1/auth/change-password` | Change your password (authenticated; current password required) |

**Brands**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/brands` | List Brands |
| POST | `/api/v1/brands` | Create Brand |
| GET | `/api/v1/brands/{brand_id}` | Brand with its official references |
| PATCH | `/api/v1/brands/{brand_id}` | Update Brand |
| POST | `/api/v1/brands/{brand_id}/references` | Register an official name/handle/domain/app/publisher/bio, or an image by perceptual hash |
| POST | `/api/v1/brands/{brand_id}/references/image` | Upload an official logo/image (validated by content; hashed with pHash) |
| DELETE | `/api/v1/brands/{brand_id}/references/{reference_id}` | Delete Reference |

**Cases & Response Workflow**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/cases` | List cases: pagination, filtering, sorting |
| POST | `/api/v1/cases` | Create a case (initial status DETECTED). Send Idempotency-Key to make retries safe. |
| GET | `/api/v1/cases/workflow` | Configured workflow transitions |
| GET | `/api/v1/cases/{case_id}` | Case detail: evidence, signals, linked entities, notes, status history, escalations |
| PATCH | `/api/v1/cases/{case_id}` | Edit title / summary / severity (`case:triage`). Send `version` for optimistic concurrency → 409 `version_conflict` on conflict. |
| DELETE | `/api/v1/cases/{case_id}` | Delete a case (administrators only). Notes/events/links cascade; entities and evidence are kept. |
| POST | `/api/v1/cases/{case_id}/assign` | Assign or reassign the owner (UNDER_REVIEW -> ASSIGNED automatically) |
| GET | `/api/v1/cases/{case_id}/assignments` | Assignments |
| POST | `/api/v1/cases/{case_id}/entities` | Link more entities to an open case |
| POST | `/api/v1/cases/{case_id}/escalate` | Record an escalation / partner handoff (legal, marketing, platform). Does NOT contact anyone or request a takedown. |
| POST | `/api/v1/cases/{case_id}/notes` | Note |
| POST | `/api/v1/cases/{case_id}/resolve` | Resolve with an outcome and summary |
| POST | `/api/v1/cases/{case_id}/status` | Validated status transition (use expected_status to guard against duplicate/racing requests) |

**Dashboard**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/dashboard/mobile-apps` | Mobile app monitoring summary |
| GET | `/api/v1/dashboard/stats` | Totals, risk/type distribution, recent detections, latest activity (database-backed) |

**Detection & Risk Scoring**

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/detection/analyze` | Analyze several entities (by ids) or every entity of a brand (max 200) |
| GET | `/api/v1/detection/assessments/{assessment_id}` | Assessment |
| GET | `/api/v1/detection/model` | Active scoring model: version, weights, thresholds, confidence formula |
| GET | `/api/v1/detection/signals` | Signal results (latest assessment per entity unless latest_only=false) |

**Detections feed** (flattened latest-assessment-per-entity view used by the web app's detection screens)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/detections` | Feed items with `entity`, `detection_type`, `signals_summary` and `status` (analyzed\|partial\|unavailable); filters `q/severity/entity_type/brand_id/status/provenance/from/to`; sort `risk_score\|confidence\|assessed_at` |
| GET | `/api/v1/detections/{assessment_id}` | Full assessment behind a detection (same shape as `/detection/assessments/{id}`) |
| POST | `/api/v1/detections/{assessment_id}/re-analyze` | Re-run the four detection families on the assessment's entity; returns the NEW assessment (history is preserved) |

**Digital Entities**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/entities` | List Entities |
| POST | `/api/v1/entities` | Submit a profile, website, domain, image or mobile app (manual/synthetic). Duplicates are merged into the existing record. |
| GET | `/api/v1/entities/{entity_id}` | Entity with its latest explainable assessment |
| POST | `/api/v1/entities/{entity_id}/analyze` | Run the four detection families and persist a new historical risk assessment |
| GET | `/api/v1/entities/{entity_id}/assessments` | Assessment history (newest first) |
| GET | `/api/v1/entities/{entity_id}/cases` | Cases this entity is part of |
| GET | `/api/v1/entities/{entity_id}/evidence` | Entity Evidence |
| POST | `/api/v1/entities/{entity_id}/inspect-url` | SSRF-guarded live URL inspection (disabled unless URL_FETCH_ENABLED=true); stores metadata as evidence |
| DELETE | `/api/v1/entities/{entity_id}` | Delete an entity (administrators only) and its stored evidence files; relationships and case history are kept/cascaded in the database |

**Digital Surface Collection**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/collection/connectors` | Available source connectors. live=false means NO real external monitoring is happening. |
| POST | `/api/v1/collection/connectors/{key}/run` | Run a connector for a brand (409 if not configured) |

**Evidence**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/evidence` | List evidence: filters `entity_id, kind, case_id (entity-linked or directly attached), verification_status (verified\|mismatch\|pending), q`; sort `created_at\|collected_at\|title\|size_bytes` |
| POST | `/api/v1/evidence` | Attach text/URL/WHOIS/other evidence metadata to an entity |
| POST | `/api/v1/evidence/upload` | Upload an image/screenshot (PNG/JPEG/WEBP/GIF, content-validated, size-limited) |
| GET | `/api/v1/evidence/export/csv` | CSV export of every evidence record in your scope (attachment download; same filters as the list) |
| GET | `/api/v1/evidence/{evidence_id}` | Evidence detail incl. case links and verification status |
| GET | `/api/v1/evidence/{evidence_id}/file` | Download the stored image (served as an attachment with nosniff) |
| POST | `/api/v1/evidence/{evidence_id}/verify` | Recompute the sha256 of the stored bytes and record verified/mismatch (honest, no fabrication) |
| POST | `/api/v1/evidence/{evidence_id}/link` | Link this evidence to a case and/or (re)attach it to an entity |
| DELETE | `/api/v1/evidence/{evidence_id}/link/{case_id}` | Remove the case link (the evidence itself is kept) |
| DELETE | `/api/v1/evidence/{evidence_id}` | Delete evidence (administrators and investigators; removes the stored file too) |

**Health**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness |
| GET | `/api/v1/ready` | Readiness (checks the database and that migrations are applied) |

**Risk Graph**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/graph` | Nodes and edges, filterable by brand, entity type, risk and edge confidence |
| GET | `/api/v1/graph/clusters` | Connected clusters with evidence-based investigation proposals |
| POST | `/api/v1/graph/clusters/case` | Open a case from a cluster (human action; never automatic) |
| POST | `/api/v1/graph/discover` | Derive relationships from observable data for a brand (shared images/domains/identity/infrastructure/posting) |
| GET | `/api/v1/graph/entities/{entity_id}/neighbors` | Neighbors |
| GET | `/api/v1/graph/entities/{entity_id}/related` | Related entities ranked by strongest-path confidence |
| POST | `/api/v1/graph/rebuild` | Rebuild the graph from persisted relationships and return its size |
| POST | `/api/v1/graph/relationships` | Record an investigator-asserted relationship (type, confidence, evidence reference) |

**Users & Organizations**

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/organizations` | Organizations visible to the caller |
| POST | `/api/v1/organizations` | Create an organization (administrator) |
| GET | `/api/v1/organizations/{org_id}` | Organization detail with `member_count`/`brand_count` (members and administrators; 403 for outsiders) |
| PATCH | `/api/v1/organizations/{org_id}` | Rename an organization (`org:manage`, audited) |
| GET | `/api/v1/users` | List users (administrator) |
| POST | `/api/v1/users` | Create a user with any role (administrator) |
| GET | `/api/v1/users/assignable` | Active investigators/admins who can own cases in the caller's scope |
| GET | `/api/v1/users/roles` | Roles and their permissions |
| GET | `/api/v1/users/{user_id}` | Get User |
| PATCH | `/api/v1/users/{user_id}` | Change role / organization / active state / password (administrator) |

**Notifications** (in-app, per user; case workflows generate `case_created/case_assigned/case_escalated/case_resolved`
notifications and high/critical assessments notify administrators)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/notifications` | Your notifications, newest first (`unread_only`, pagination) + `unread_count` |
| POST | `/api/v1/notifications/read` | Mark notifications read (omit `ids` to mark ALL) |

**Integrations** (per organization; configurations encrypted at rest with Fernet derived from `SECRET_KEY`;
secret values are NEVER returned — the preview masks them as `••••`; `test` never fakes success)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/integrations` | Provider catalog (x_twitter, instagram, google_play, app_store, web_scraping, dns_whois, url_scan) merged with stored status |
| GET | `/api/v1/integrations/{key}` | One provider + stored configuration (masked) |
| POST | `/api/v1/integrations/{key}/connect` | Validate + encrypt the configuration (`connector:run`) |
| POST | `/api/v1/integrations/{key}/disconnect` | Remove the stored configuration |
| POST | `/api/v1/integrations/{key}/test` | Honest connectivity test: real DNS/HTTP for dns_whois/web_scraping; credential providers report "unverified" instead of fake success |
| POST | `/api/v1/integrations/{key}/sync` | Run the sample connector (SYNTHETIC data, stated in the response) for configured store providers; 400 `no_connector_available` otherwise |

**App Monitoring** (store packages per brand; linked to a `mobile_app` entity through the normal ingestion pipeline,
provenance=synthetic until a real store integration is configured)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/monitoring/apps` | Monitored apps with linked entity risk; filters `q/brand_id/risk_severity/monitoring_status`, sort/order, pagination |
| POST | `/api/v1/monitoring/apps` | Start monitoring a package (validates package id + store URL; 409 `duplicate_monitoring_target`) |
| PATCH | `/api/v1/monitoring/apps/{id}` | Pause/resume or correct the store URL |
| DELETE | `/api/v1/monitoring/apps/{id}` | Stop monitoring (the linked entity is kept) |
| POST | `/api/v1/monitoring/apps/{id}/sync` | Update attributes from the synthetic sample connector and re-run the analysis (message says "synthetic" explicitly) |

**Reports** (`from`/`to` ISO dates, default last 30 days; `brand_id` optional)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/reports/overview` | Totals, threat distribution, cases by status, daily risk trend, entities-at-risk by channel, top connected entities, mobile apps, evidence, `data_notes` (`dashboard:read`) |
| GET | `/api/v1/reports/export/csv` | CSV attachment: `report=threats\|cases\|entities\|apps\|evidence` (`entity:read`/`case:read`/`evidence:read`) |

_Total: 97 operations._

## Known limitations
* No live collection, no scraping, no real app-store/social integrations (abstractions + synthetic sample only). Private/closed surfaces are out of scope by design.
* Heuristic, unvalidated scoring; no ML embeddings. Image matching is pHash only (robust to resizing/light edits, not to heavy crops/overlays).
* Registrable-domain extraction uses a small built-in multi-part-suffix list, not the full Public Suffix List.
* "Publisher" is an attribute of apps, not a separate graph node type. Graph is rebuilt per request (fine for thousands of entities; cache/Neo4j for larger builds).
* Discovery compares up to 200 most-recent entities per brand (O(n²)); coordination analysis compares against up to 500 peers.
* In-memory rate limiting is per process. Uploaded files live on local disk. HS256 JWTs, no refresh tokens/revocation list (deactivate the user to cut access).
* Dockerfile/docker-compose were written and syntax-checked but **not executed** in the authoring environment (no Docker available there); the native
  PostgreSQL path (migrations, seed, server, 286 tests) was executed.

## Publish as a separate GitHub repository

Create an empty GitHub repository, then run these commands from this directory:

```bash
git init -b main
git add .
git commit -m "Initial backend project"
git remote add origin https://github.com/YOUR-USER/YOUR-BACKEND-REPO.git
git push -u origin main
```

The `.env` file, virtual environments, and uploaded files are excluded by `.gitignore`.
