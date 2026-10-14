# Anarisk — Nimbus Ninjas

Nimbus Ninjas is a digital threat intelligence & investigation platform for identifying impersonation, lookalike websites, fake social profiles, and suspicious mobile apps. The project combines a FastAPI backend, a PostgreSQL data model, graph-based relationship analysis, and a React frontend to help investigators assess risk, review evidence, and manage response cases.

## Documentation

| Document | Contents |
|---|---|
| [docs/API.md](docs/API.md) | Full API reference (generated from the live OpenAPI schema — 97 endpoints) |
| [docs/STATUS.md](docs/STATUS.md) | Feature checklist, verification evidence, and known limitations |
| [PLAN.md](PLAN.md) | Architecture, routes, and design-system plan |
| Interactive API docs | http://localhost:8000/docs (Swagger) once the API is running |

This repository implements the Nimbus Ninjas architecture for digital risk protection and case review:

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
- http://localhost:3000

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

The API exposes 97 endpoints across 16 groups (see [docs/API.md](docs/API.md) for the generated reference):

- authentication (login, register, forgot/reset password, profile, preferences, change password)
- users, organizations, and role management
- brands and official references (name, handle, domain, image, app package)
- digital entities with server-side search, filtering, sorting, and pagination
- detection and explainable scoring (4 signal families, rule-based heuristics)
- graph analysis (relationship graph, neighbors, clusters, rebuild)
- workflow-based case management (assignment, escalation, resolution, notes, events, optimistic concurrency)
- evidence (upload, SHA-256 verification, link/unlink, download, CSV export)
- notifications (unread counts, mark read)
- integrations catalog (7 providers with honest connection status, test/sync/disconnect)
- monitoring targets for mobile apps (add, pause, sync, remove)
- reports (overview aggregates, risk trend, CSV export)
- dashboard metrics and audit history

## Frontend

The React app is a 12-interface premium light-theme workspace: Login (with registration and
password recovery), Overview Dashboard, Digital Assets, Entity Details, Threat Intelligence,
Risk Graph, Investigations (case list + case workspace), Mobile Apps, Evidence Center,
Reports & Analytics, and Settings (profile, workspace, team, brands, integrations,
monitoring, notifications, security). Every control talks to the real API — there is no
mock data layer and no fake "connected" integration states.

## Verification and tests

Backend tests are available:

```bash
cd backend
pytest
```

The project includes automated tests covering authentication, RBAC, detection logic, graph analysis, case workflows, and migration safety.

## License

This project is currently provided as a source repository for development and demonstration purposes. Add a license file if you plan to publish or distribute it.

## Next steps

If you want to extend the platform, the natural next areas are:

- adding real data connectors for social and app marketplaces
- improving signal quality with labeled datasets
- adding richer frontend workflows and analytics
- integrating automated notification and response actions

