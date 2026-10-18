# AnaRisk

AnaRisk is a digital threat intelligence & investigation platform for identifying impersonation, lookalike websites, fake social profiles, and suspicious mobile apps. The project combines a FastAPI backend, a PostgreSQL data model, graph-based relationship analysis, and a React frontend to help investigators assess risk, review evidence, and manage response cases.

## Documentation

| Document | Contents |
|---|---|
| [docs/API.md](docs/API.md) | Full API reference (generated from the live OpenAPI schema — 107 endpoints / 18 tags) |
| [docs/STATUS.md](docs/STATUS.md) | Feature checklist, verification evidence, and known limitations |
| [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md) | Email OTP verification & password reset: Resend / Gmail SMTP setup, testing, troubleshooting |
| [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) | Production deployment: Render backend + Vercel frontend, env vars, verification checklist |
| [PLAN.md](PLAN.md) | Architecture, routes, and design-system plan |
| Interactive API docs | http://127.0.0.1:8000/docs (Swagger) once the API is running |

> **Note on `127.0.0.1` vs `localhost`:** on machines where local DNS resolution of
> `localhost` is slow or broken (as in this build environment), address everything via
> `127.0.0.1` — database URLs, uvicorn, the Vite dev server (`npx vite --host 127.0.0.1`),
> and the Vite API proxy target. See [docs/STATUS.md](docs/STATUS.md).

This repository implements the AnaRisk architecture for digital risk protection and case review:

- Digital Surface Collection
- Detection Engine
- Risk Graph
- Explainable Case Review
- Response & Resolution

## What this project does

Anarisk helps teams monitor and investigate brand abuse by:

- ingesting digital entities such as domains, profiles, apps, and websites
- scoring them using explainable signal families
- linking suspicious entities through relationship graphs
- managing investigation cases with status workflows and ownership
- reviewing evidence and risk assessments in a dashboard
- enforcing role-based access and organization-level isolation

## Key features

- Risk scoring with explainable signals
  - brand logo matching
  - impersonation detection
  - URL/domain risk analysis
  - behavioral and coordination analysis
- Graph-based investigation of related entities and suspicious clusters
- Case workflow with assignment, escalation, notes, and resolution tracking
- Evidence uploads and provenance-aware assessments
- Security controls including RBAC, tenancy scoping, SSRF protections, and upload validation
- Email authentication: signup with a crypto-secure 6-digit email OTP (hash-only storage,
  TTL, attempt lockout, resend cooldown, no account enumeration), single-use
  password-reset tokens, resend verification — via pluggable transports
  (`none` dev / SMTP / Resend / memory). See [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md)
  with per-message delivery logs
- Investigation tools: phishing/URL scanner, suspicious email analyzer, job-offer checker,
  social profile verifier — each finding carries status, severity, evidence, source, and
  an explicit limitation (risk ≠ confidence; never fabricated)
- AI assistant with provider abstraction (OpenAI-compatible or retrieval-only mode),
  grounding against retrieved platform records with citation validation, and
  prompt-injection defense
- Background monitoring scheduler (DB-backed, `FOR UPDATE SKIP LOCKED` claims, retry
  with backoff, admin notification on repeated failure) driving alerts and watchlists
- Demo-ready synthetic dataset for local testing and walkthroughs

## Tech stack

Backend
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Pydantic
- NetworkX
- RapidFuzz
- Pillow + ImageHash

Frontend
- React
- Vite
- TypeScript
- Tailwind CSS
- Recharts
- React Flow / XYFlow

## Repository structure

```text
.
├── backend/              # FastAPI API, migrations, database models, services, tests
├── frontend/             # React + Vite dashboard application
├── README.md             # Project overview
├── .gitignore
└── ...
```

## Quick start

### Option 1: Run with Docker (recommended)

From the backend directory:

```bash
cd backend
cp .env.example .env
docker compose up --build
```

This starts the API and PostgreSQL services. The app is available at:

- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

Optional demo data:

```bash
cd backend
docker compose run --rm api python -m scripts.seed
```

### Option 2: Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

Then run the frontend separately:

```bash
cd frontend
npm install
npm run dev
```

Frontend dev server:
- http://127.0.0.1:3000 — `npm run dev` binds `127.0.0.1` explicitly (local `localhost`
  DNS resolution is unreliable on some machines)

## Environment variables

Backend (set in `backend/.env` or the process environment):

| Variable | Values / default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` | Database DSN. Use `127.0.0.1` instead of `localhost` if local DNS is slow |
| `TEST_DATABASE_URL` | `postgresql+psycopg://…` | Database used by pytest (wiped per run) |
| `ENVIRONMENT` | `development` / `production` | Development exposes `dev_otp` / `dev_reset_token` in API responses; production never does |
| `EMAIL_PROVIDER` | `none` (default) / `smtp` / `resend` / `memory` | Email transport for the signup OTP and password reset. `none` = no delivery (dev-only `dev_otp` outside production; honest `email_sent=false`). `smtp` needs `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, plus `EMAIL_FROM_ADDRESS` / `EMAIL_FROM_NAME`. `resend` needs `RESEND_API_KEY` + a verified sender domain. `memory` captures messages in-process (tests). Production with no provider → honest 503 on password reset, `delivery_failed` on signup. Setup: [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md) |
| `OTP_TTL_MINUTES` | `10` (default) | How long a signup verification code stays valid |
| `OTP_MAX_ATTEMPTS` | `5` (default) | Wrong guesses per code before it is locked out |
| `RESEND_VERIFICATION_COOLDOWN_SECONDS` | `60` (default) | Per-email throttle on resend (applies uniformly, so it never discloses account existence) |
| `FRONTEND_URL` | `http://127.0.0.1:3000` | Base URL used in password-reset links |
| `AI_PROVIDER` | `none` (default) / `openai-compatible` / `memory` | Assistant provider. `none` = retrieval mode (honest status shown in UI). `openai-compatible` needs `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`. Provider errors and malformed output fall back to retrieval mode |
| `BOOTSTRAP_ADMIN_PASSWORD` | string | Password for the bootstrap admin on seed |

Scheduler: runs in the API process lifespan; configured with `MONITORING_WORKER_ENABLED`
(default `true`), `MONITORING_INTERVAL_SECONDS` (default `300`), `MONITORING_RETRY_MAX`
(default `3`), and `MONITORING_BACKOFF_SECONDS` (default `120`). Targets are claimed with
`FOR UPDATE SKIP LOCKED`, retried with backoff, and admins are notified after repeated
failure.

## Demo accounts

The seed script creates development accounts for testing:

| Email | Role | Password |
|---|---|---|
| admin@nimbus.example | administrator | `BOOTSTRAP_ADMIN_PASSWORD` (default `ChangeMe-Admin-123`) |
| investigator@nimbus.example | investigator | `Demo-Passw0rd!` |
| investigator2@nimbus.example | investigator | `Demo-Passw0rd!` |
| analyst@nimbus.example | investigator | `Demo-Passw0rd!` |
| owner@nimbus.example | brand_owner | `Demo-Passw0rd!` |
| partner@nimbus.example | partner | `Demo-Passw0rd!` |

## Important project note

This project is designed as a demo and research platform. By default:

- no live monitoring connectors are configured
- data is synthetic or manually submitted unless a real connector is enabled
- risk scoring is heuristic and meant for human review
- case actions do not contact external parties automatically

## Backend API summary

The API exposes 107 endpoints across 18 groups (see [docs/API.md](docs/API.md) for the generated reference):

- authentication (register with email OTP verification, login, forgot/reset password,
  resend verification code, verify email code, profile, preferences, change password)
- users, organizations, and role management
- brands and official references (name, handle, domain, image, app package)
- digital entities with server-side search, filtering, sorting, and pagination
- detection and explainable scoring (4 signal families, rule-based heuristics)
- graph analysis (relationship graph, neighbors, clusters, rebuild)
- workflow-based case management (assignment, escalation, resolution, notes, events, optimistic concurrency)
- evidence (upload, SHA-256 verification, link/unlink, download, CSV export)
- investigation tools (URL/phishing scanner, suspicious email analyzer, job-offer checker,
  social profile verifier, analysis history) — findings with status/severity/evidence/source/limitation
- AI assistant (grounded answers with validated citations, provider status, chat history)
- notifications (unread counts, mark read) and watchlists
- integrations catalog (7 providers with honest connection status, test/sync/disconnect)
- monitoring targets (add, pause, sync, remove) + DB-backed background scheduler
- reports (overview aggregates, risk trend, CSV export)
- dashboard metrics and audit history

## Frontend

The React app is a 15-interface premium light-theme workspace: Login (with registration,
OTP verification states — sending / sent / dev code / delivery failure / resend cooldown —
and password recovery), Verify Email (6-digit code entry), Overview Dashboard,
Digital Assets, Entity Details, Threat Intelligence, Risk Graph, Investigations (case list +
case workspace), Investigate (4 analysis tools + run history), AI Assistant, Alerts
(notifications + watchlists), Mobile Apps, Evidence Center, Reports & Analytics, and
Settings (profile, workspace, team, brands, integrations, monitoring, notifications,
security). Every control talks to the real API — there is no mock data layer and no fake
"connected" integration states.

## Verification and tests

Backend test suite (348 tests, exit 0 in this environment):

```bash
cd backend
# point TEST_DATABASE_URL at a disposable Postgres DB first
pytest -q
```

The suite covers authentication, email OTP verification (delivery, invalid/expired/locked
codes, reuse, cooldown, rate limits, provider failures, no enumeration) and password reset, RBAC, detection logic, graph
analysis, case workflows, evidence, integrations, monitoring, the background scheduler,
the four investigation tools (network calls monkeypatched for determinism), the AI
assistant (grounding, citation validation, prompt-injection defense, provider fallback),
and migration safety. Frontend verification is `npx tsc --noEmit` + `npm run build` +
browser E2E against the live API. Full evidence: [docs/STATUS.md](docs/STATUS.md).

## License

This project is currently provided as a source repository for development and demonstration purposes. Add a license file if you plan to publish or distribute it.

## Next steps

If you want to extend the platform, the natural next areas are:

- adding real data connectors for social and app marketplaces
- improving signal quality with labeled datasets
- adding richer frontend workflows and analytics
- integrating automated notification and response actions

