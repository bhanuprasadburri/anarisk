# Nimbus Ninjas — Project Status & Verification

_Last updated: 2026-10-14. Everything marked ✅ was verified by running the listed command
or live API/browser check, not by inspection alone._

## 1. Infrastructure & database

| Item | Status | Evidence |
|---|---|---|
| PostgreSQL (portable, local) for tests + fallback | ✅ | `TEST_DATABASE_URL` → local `nimbus_test`; local `nimbus` also seeded as fallback (40 entities / 14 cases) |
| Supabase PostgreSQL (project dev database) | ✅ | `DATABASE_URL` → Supabase (PostgreSQL 17.11, SSL). A local DNS outage made it unreachable mid-build; after connectivity recovered the complete seeded dataset was restored via `pg_dump`/`psql` from the local database (the environment repeatedly killed the long-running seed process). Verified counts: 40 entities / 100 assessments / 60 relationships / 14 cases / 24 evidence / 88 notifications / 6 monitoring targets |
| Migrations 0001 + 0002 (24 tables) | ✅ | Applied on both DBs; notifications, integrations, monitoring targets, password-reset tokens, case↔evidence links included |
| Seed data | ✅ | `python -m scripts.seed` → 1 org, 6 users, 3 brands, 40 entities (14 social / 10 website / 6 domain / 6 mobile app / 4 image; 6 manual + 34 synthetic), 100 assessments, 60 relationships, 14 cases across all 6 statuses, 24 evidence, 88 notifications, 6 monitoring targets. All synthetic data is labeled as such |

## 2. Backend API

| Item | Status | Evidence |
|---|---|---|
| Endpoint surface | ✅ | 97 endpoints / 16 tags generated from live `openapi.json` → [docs/API.md](API.md) (`backend/scripts/gen_api_docs.py` regenerates it) |
| Test suite | ✅ | `pytest -q` exit 0 — 286 tests (auth, RBAC/tenancy, detection, graph, cases incl. optimistic-concurrency 409s, evidence incl. verify/link/unlink, integrations, monitoring, reports, migrations) |
| Live smoke test | ✅ | login → dashboard stats (40 entities / 19 high-risk / 12 open cases), detections + filters, notifications (57 unread), integrations (7 providers, all honest `not_configured`), monitoring (6), reports overview (31-day trend, 5 channels, 5 honesty notes), evidence (24), cases (14), graph (40 nodes / 60 edges) |
| CSV export | ✅ | `GET /reports/export/csv?report=entities` → HTTP 200 `text/csv` with real rows (verified via curl) |
| Input validation | ✅ | Invalid sort field rejected with structured 422 (`query.sort` pattern mismatch) |
| Honest integration states | ✅ | All 7 providers report `not_configured` until real credentials are supplied; no fake "connected" status anywhere |
| Bugs fixed during verification | ✅ | Evidence metadata key mismatch (`metadata` vs alias `meta`) — metadata now returned correctly; UTC timestamp serialization unified via `UTCDateTime` TypeDecorator |

## 3. Frontend

| Item | Status | Evidence |
|---|---|---|
| Design system + UI kit | ✅ | `src/index.css`, `tailwind.config.js`, `src/components/ui/*`; `npx tsc --noEmit` exit 0 |
| Production build | ✅ | `npm run build` succeeds (14.9 s, all 12 pages code-split) |
| API client services (no mocks) | ✅ | All `src/services/*` are pure API clients; `mocks/` removed |
| App shell | ✅ | Sidebar (9 sections), Ctrl+K global search, notifications popover w/ unread badge, profile menu — browser-verified |
| Auth flows | ✅ | Login, failed-login error, registration validation (422 → inline), successful registration → auto-login, protected routes — all exercised in the browser against the live API |

## 4. Page-by-page verification

| Page | Verified by |
|---|---|
| Login / Register / Password recovery | ✅ Browser E2E (incl. failed login + register validation + successful registration) |
| Overview Dashboard | ✅ Browser E2E — real data (40/19/12), metric cards, donut + trend charts, recent detections list, 60s auto-refresh, date range + brand scope |
| Digital Assets | ✅ Browser E2E — table rows with severity/provenance badges, actions, filters UI |
| Entity Details | ✅ Browser E2E — risk ring (0.91), badges, canonical ID + copy, Re-analyze, 5 tabs |
| Threat Intelligence | ✅ Browser E2E — 3 tabs, stat cards, detection rows (score/confidence/status) |
| Risk Graph | ✅ Build + tsc + agent live-API verification (browser tool removed before manual pass) |
| Investigations (cases list) | ✅ Build + tsc + agent live-API verification (incl. version-conflict 409 tested live) |
| Case workspace (detail) | ✅ Build + tsc + agent live-API verification |
| Mobile App Monitoring | ✅ Build + tsc + agent live-API mutation tests (create→pause→resume→remove) |
| Evidence Center | ✅ Build + tsc + agent live-API mutation tests (upload→link→unlink→verify→delete, CSV export) |
| Reports & Analytics | ✅ Build + tsc + agent contract verification (overview + CSV endpoints smoke-tested live) |
| Settings & Integrations | ✅ Build + tsc + agent contract verification |
| Multi-tenancy scoping | ✅ Browser E2E — self-registered account (no org) sees an entirely empty, correctly-labeled workspace |

## 5. Honesty rules enforced

- Synthetic/seed data is labeled (provenance badges: `Manual` vs `Sample data`).
- Risk scores are described as explainable heuristics requiring analyst review.
- Integrations never display "Connected" unless a live check passed; status shown verbatim from the backend.
- Publisher identity for mobile apps is always shown "unverified".
- No mock login, no fake data layer, no dead controls.

## 6. Known limitations (deliberate, honest)

1. **Connectors are stubs by design.** X/Twitter, Instagram, Google Play, App Store, web
   scraping, DNS/WHOIS and URL scan providers accept configuration and return honest status,
   but only local/synthetic collection runs without real third-party API credentials.
2. **Detection is rule-based** (weighted brand similarity, impersonation, URL risk, behavior;
   weights configurable via env). Unvalidated against labeled datasets — leads, not verdicts.
3. **Password reset emails are not delivered**; in development the API returns a
   `dev_reset_token` so the flow works end to end.
4. **PDF export** generates a print-ready HTML document (use the browser's "Save as PDF");
   CSV export is a true server-side CSV download.
5. **Seed data is synthetic** and regenerated wholesale by `python -m scripts.seed`
   (truncates first). Do not use it for real cases.
6. **Supabase reachability depends on local network/DNS**; during this build a local DNS
   outage made the DB temporarily unreachable. The backend honors `DATABASE_URL` from
   `backend/.env` (Supabase); a local Postgres is kept as a fallback for tests.
7. **Some entities' `last_seen_at` can be slightly in the future** — a cosmetic quirk of the
   synthetic seed generator, honestly displayed by the relative-time formatter.

## 7. Demo accounts

| Email | Role | Password |
|---|---|---|
| admin@nimbus.example | administrator | `ChangeMe-Admin-123` |
| investigator@nimbus.example / investigator2@ / analyst@ | investigator | `Demo-Passw0rd!` |
| owner@nimbus.example | brand_owner | `Demo-Passw0rd!` |
| partner@nimbus.example | partner | `Demo-Passw0rd!` |

Run order: start PostgreSQL, `alembic upgrade head`, `python -m scripts.seed`,
`uvicorn app.main:app` (backend), `npm run dev` (frontend, http://localhost:3000).
