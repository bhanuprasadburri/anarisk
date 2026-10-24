# AnaRisk — API Reference

Generated from the current FastAPI OpenAPI schema (`GET /openapi.json`, interactive docs at `/docs`).
Base URL: `http://127.0.0.1:8000/api/v1` — **115 endpoints** across 19 tags.

Authentication: `Authorization: Bearer <JWT>` (obtain via `POST /auth/login`).
Role checks are enforced server-side per endpoint; unauthenticated requests return 401,
missing permissions return 403.

## AI Assistant (2)

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/assistant/ask` | Ask a question about your records. Answers cite retrieved record ids; uses the configured AI provider or deterministic retrieval when none is set. |
| GET | `/api/v1/assistant/status` | AI provider status (honest: never claims a provider that is not configured) |

## Audit (1)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/audit` | Audit history (administrators: all; others: own organization only) |

## Authentication (10)

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/auth/change-password` | Change your password (authenticated; current password required) |
| POST | `/api/v1/auth/forgot-password` | Request a password-reset link. Always 200 - unknown emails behave like known ones (no user enumeration). |
| POST | `/api/v1/auth/login` | Login with JSON credentials |
| GET | `/api/v1/auth/me` | Current user (incl. preferences and organization summary) |
| PATCH | `/api/v1/auth/me` | Update your own profile (full name, email, preferences) |
| POST | `/api/v1/auth/register` | Self-register (brand_owner role). Individual signups receive a personal organization with the brand 'Self'; pass organization_name for an organization signup. Creates the account UNVERIFIED and emails a 6-digit OTP (uniform response whether or not the address already exists — no account enumeration). dev_otp only outside production with no email provider configured. |
| POST | `/api/v1/auth/resend-verification` | Resend the signup OTP (or a generic notice). Uniform for unknown/verified/pending addresses (no enumeration); per-email cooldown; email_sent reports honest delivery. |
| POST | `/api/v1/auth/reset-password` | Set a new password with a valid reset token (400 invalid_or_expired_token otherwise) |
| POST | `/api/v1/auth/token` | OAuth2 password form (used by Swagger 'Authorize') |
| POST | `/api/v1/auth/verify-email` | Confirm the 6-digit OTP from the verification email (single-use, attempt-limited, TTL-bound). Generic 400 on any failure — never reveals whether the address exists. |

## Brands (7)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/brands` | List Brands |
| POST | `/api/v1/brands` | Create Brand |
| GET | `/api/v1/brands/{brand_id}` | Brand with its official references |
| PATCH | `/api/v1/brands/{brand_id}` | Update Brand |
| POST | `/api/v1/brands/{brand_id}/references` | Register an official name/handle/domain/app/publisher/bio, or an image by perceptual hash |
| POST | `/api/v1/brands/{brand_id}/references/image` | Upload an official logo/image (validated by content; hashed with pHash) |
| DELETE | `/api/v1/brands/{brand_id}/references/{reference_id}` | Delete Reference |

## Cases & Response Workflow (15)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/cases` | List cases: pagination; filters q, status, severity, brand_id, assignee_id, mine, unassigned, entity_id, open_only, min_risk; sort created_at\|updated_at\|risk_score\|confidence\|case_number\|severity |
| POST | `/api/v1/cases` | Create a case (initial status DETECTED). Send Idempotency-Key to make retries safe. |
| GET | `/api/v1/cases/workflow` | Configured workflow transitions |
| DELETE | `/api/v1/cases/{case_id}` | Delete a case (administrators only). Notes/events/links cascade; entities and evidence are kept |
| GET | `/api/v1/cases/{case_id}` | Case detail: evidence, signals, linked entities, notes, status history, escalations |
| GET | `/api/v1/cases/{case_id}/takedown-report` | Confirmed case only; returns an evidence-backed draft for analysts with `case:resolve`. Does not submit it. |
| PATCH | `/api/v1/cases/{case_id}` | Edit title / summary / severity / platforms (case:triage). Send `version` for optimistic concurrency -> 409 on conflict |
| POST | `/api/v1/cases/{case_id}/assign` | Assign or reassign the owner (UNDER_REVIEW -> ASSIGNED automatically) |
| GET | `/api/v1/cases/{case_id}/assignments` | Assignments |
| POST | `/api/v1/cases/{case_id}/entities` | Link more entities to an open case |
| POST | `/api/v1/cases/{case_id}/escalate` | Record an escalation / partner handoff (legal, marketing, platform). Does NOT contact anyone or request a takedown. |
| GET | `/api/v1/cases/{case_id}/graph` | Case sub-graph: the case's linked entities + relationships among them (composed server-side, brand-scoped) |
| POST | `/api/v1/cases/{case_id}/notes` | Note |
| POST | `/api/v1/cases/{case_id}/resolve` | Resolve with an outcome and summary |
| POST | `/api/v1/cases/{case_id}/status` | Validated status transition (use expected_status to guard against duplicate/racing requests) |

## Digital Surface Collection (2)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/collection/connectors` | Available source connectors. live=false means NO real external monitoring is happening. |
| POST | `/api/v1/collection/connectors/{key}/run` | Run a connector for a brand (409 if not configured) |

## Dashboard (2)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/dashboard/mobile-apps` | Mobile app monitoring summary |
| GET | `/api/v1/dashboard/stats` | Totals, risk/type distribution, recent detections, latest activity (database-backed) |

## Detection & Risk Scoring (7)

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/detection/analyze` | Analyze several entities (by ids) or every entity of a brand (max 200) |
| GET | `/api/v1/detection/assessments/{assessment_id}` | Assessment |
| GET | `/api/v1/detection/model` | Active scoring model: version, weights, thresholds, confidence formula and plain-English rule descriptions |
| GET | `/api/v1/detection/signals` | Signal results (latest assessment per entity unless latest_only=false) |
| GET | `/api/v1/detections` | Flattened latest assessment per entity: filters q, severity, entity_type, brand_id, status, provenance, from, to; sort risk_score\|confidence\|assessed_at |
| GET | `/api/v1/detections/{assessment_id}` | Full assessment behind a detection (same shape as /detection/assessments/{id}) |
| POST | `/api/v1/detections/{assessment_id}/re-analyze` | Re-run the four detection families on the assessment's entity; returns the NEW assessment (history is preserved) |

## Digital Entities (9)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/entities` | List Entities |
| POST | `/api/v1/entities` | Submit a profile, website, domain, image or mobile app (manual/synthetic). Duplicates are merged into the existing record. |
| DELETE | `/api/v1/entities/{entity_id}` | Delete an entity and its evidence (administrators only). Linked cases keep their history |
| GET | `/api/v1/entities/{entity_id}` | Entity with latest assessment, related entities, cases, evidence and asset metadata |
| POST | `/api/v1/entities/{entity_id}/analyze` | Run the four detection families and persist a new historical risk assessment |
| GET | `/api/v1/entities/{entity_id}/assessments` | Assessment history (newest first) |
| GET | `/api/v1/entities/{entity_id}/cases` | Cases this entity is part of |
| GET | `/api/v1/entities/{entity_id}/evidence` | Entity Evidence |
| POST | `/api/v1/entities/{entity_id}/inspect-url` | SSRF-guarded live URL inspection (disabled unless URL_FETCH_ENABLED=true); stores metadata as evidence |

## Evidence (13)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/evidence` | List evidence: filters entity_id, kind, case_id (entity-linked or directly attached), verification_status, q; sort created_at\|collected_at\|title\|size_bytes |
| POST | `/api/v1/evidence` | Attach text/URL/WHOIS/other evidence metadata to an entity |
| GET | `/api/v1/evidence/export` | CSV export of every evidence record in your scope (alias used by the web app) |
| GET | `/api/v1/evidence/export/csv` | CSV export of every evidence record in your scope (attachment download) |
| POST | `/api/v1/evidence/upload` | Upload an image/screenshot (PNG/JPEG/WEBP/GIF, content-validated, size-limited) |
| DELETE | `/api/v1/evidence/{evidence_id}` | Delete evidence (administrators and investigators; removes the stored file too) |
| GET | `/api/v1/evidence/{evidence_id}` | Evidence detail incl. case links and verification status |
| GET | `/api/v1/evidence/{evidence_id}/download` | Authenticated download (same bytes as /file; used by the web app's save dialog) |
| GET | `/api/v1/evidence/{evidence_id}/file` | Download the stored image (served as an attachment with nosniff) |
| DELETE | `/api/v1/evidence/{evidence_id}/link` | Remove the case and/or entity link given as query parameters (web app variant) |
| POST | `/api/v1/evidence/{evidence_id}/link` | Link this evidence to a case and/or (re)attach it to an entity |
| DELETE | `/api/v1/evidence/{evidence_id}/link/{case_id}` | Remove the case link (the evidence itself is kept) |
| POST | `/api/v1/evidence/{evidence_id}/verify` | Recompute the sha256 of the stored bytes and record verified/mismatch (honest, no fabrication) |

## Feedback (3)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/feedback` | All feedback submissions (administrators only; filter by status/category) |
| POST | `/api/v1/feedback` | Submit feedback (bug/feature/content/other) for your brand scope |
| PATCH | `/api/v1/feedback/{feedback_id}` | Set a submission's status (administrators only) |

## Risk Graph (8)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/graph` | Nodes and edges, filterable by brand, entity type, risk and edge confidence |
| GET | `/api/v1/graph/clusters` | Connected clusters with evidence-based investigation proposals |
| POST | `/api/v1/graph/clusters/case` | Open a case from a cluster (human action; never automatic) |
| POST | `/api/v1/graph/discover` | Derive relationships from observable data for a brand (shared images/domains/identity/infrastructure/posting) |
| GET | `/api/v1/graph/entities/{entity_id}/neighbors` | Neighbors |
| GET | `/api/v1/graph/entities/{entity_id}/related` | Related entities ranked by strongest-path confidence |
| POST | `/api/v1/graph/rebuild` | Rebuild the graph from persisted relationships and return its size |
| POST | `/api/v1/graph/relationships` | Record an investigator-asserted relationship (type, confidence, evidence reference) |

## Health (2)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/health` | Liveness |
| GET | `/api/v1/ready` | Readiness (checks the database and that migrations are applied) |

## Integrations (6)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/integrations` | Provider catalog merged with stored config (admin only). Secret values are never returned (secrets echo as ••••). |
| GET | `/api/v1/integrations/{key}` | One provider + stored configuration, admin only (never secrets) |
| POST | `/api/v1/integrations/{key}/connect` | Validate + encrypt (Fernet) the configuration and mark the provider 'configured' (admin only) |
| POST | `/api/v1/integrations/{key}/disconnect` | Remove the stored configuration (back to 'not_configured', admin only) |
| POST | `/api/v1/integrations/{key}/sync` | Run the matching sample connector (synthetic data) for a configured provider; 400 no_connector_available otherwise (admin only) |
| POST | `/api/v1/integrations/{key}/test` | Honest connectivity test: real DNS/HTTP checks where possible; credential providers report 'unverified' rather than fake success (admin only) |

## App Monitoring (5)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/monitoring/apps` | Monitored apps: package, store, status + linked entity risk. Filters: q, store, brand_id, risk_severity, monitoring_status, sort, order |
| POST | `/api/v1/monitoring/apps` | Start monitoring a package. Validates the package id + store URL; 409 duplicate_monitoring_target on repeats |
| DELETE | `/api/v1/monitoring/apps/{target_id}` | Stop monitoring this package (the linked entity is kept) |
| PATCH | `/api/v1/monitoring/apps/{target_id}` | Pause/resume monitoring or correct the store URL |
| POST | `/api/v1/monitoring/apps/{target_id}/sync` | Run the sample connector for this app (SYNTHETIC data - stated honestly) and re-analyze the linked entity |

## Notifications (4)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/notifications` | Your notifications (newest first) plus a top-level unread_count |
| POST | `/api/v1/notifications/broadcast` | Administrator announcement: persists one in-app notification for every active user (delivery counts are reported honestly — rows are only counted once stored) |
| POST | `/api/v1/notifications/read` | Mark notifications read (omit ids to mark ALL read) |
| DELETE | `/api/v1/notifications/{notification_id}` | Delete one of your notifications (administrators may delete any user's) |

## Users & Organizations (10)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/organizations` | Organizations visible to the caller |
| POST | `/api/v1/organizations` | Create an organization (administrator) |
| GET | `/api/v1/organizations/{org_id}` | Organization detail (members and administrators) |
| PATCH | `/api/v1/organizations/{org_id}` | Rename an organization (org:manage) |
| GET | `/api/v1/users` | List users (administrator) |
| POST | `/api/v1/users` | Create a user with any role (administrator) |
| GET | `/api/v1/users/assignable` | Active investigators/admins who can own cases in the caller's scope |
| GET | `/api/v1/users/roles` | Roles and their permissions |
| GET | `/api/v1/users/{user_id}` | Get User |
| PATCH | `/api/v1/users/{user_id}` | Change role / organization / active state / password (administrator) |

## Reports (2)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/reports/export/csv` | CSV export: report=threats\|cases\|entities\|apps\|evidence (attachment download) |
| GET | `/api/v1/reports/overview` | Aggregate risk/case/evidence overview for a date range (empty DB returns zeros) |

## Investigation Tools (7)

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/tools/analyses` | List your organization's past tool runs (newest first) |
| GET | `/api/v1/tools/analyses/{analysis_id}` | Fetch one stored analysis |
| POST | `/api/v1/tools/email/analyze` | Analyze a pasted email or uploaded .eml for phishing signals (sender, SPF/DMARC, links, language, attachments metadata) |
| POST | `/api/v1/tools/image/analyze` | Analyze an uploaded image: content-based validation, official-logo perceptual similarity, embedded metadata and (when configured) AI review of the content — context: email \| job_offer \| social_profile |
| POST | `/api/v1/tools/job/analyze` | Assess a job offer / recruiter (employer identity, email-domain mismatch, fee requests, application link) |
| POST | `/api/v1/tools/social/analyze` | Assess a social profile against official brand references (handles, names, linked domains). Provider-verified identity is only claimed when a real platform connector is configured. |
| POST | `/api/v1/tools/url/analyze` | Scan a URL: canonicalisation, DNS (public-only), TLS certificate, SPF/DMARC, lookalike domain, offline heuristics; live fetch only when URL_FETCH_ENABLED=true |

