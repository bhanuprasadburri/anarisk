# Supabase Auth and PostgreSQL cutover

AnaRisk keeps FastAPI on Render and React on Vercel. Supabase provides Auth and PostgreSQL. The React app uses Supabase Auth only; all application data remains behind FastAPI and SQLAlchemy.

## What the repository currently contains

- FastAPI uses SQLAlchemy and Alembic revisions `0001` through `0011` for the application schema. The Render Blueprint previously created a separate Render PostgreSQL database.
- AnaRisk users have UUID IDs. Roles, organizations, brands, and API authorization are stored and checked by the backend. Cases, entities, risk assessments, evidence, notifications, integrations, and audit records keep their existing keys and relationships.
- Revision `0010` adds nullable unique `users.supabase_user_id`. Revision `0011` enables RLS on all AnaRisk application tables without creating browser policies. They leave all AnaRisk IDs and existing records intact. The first confirmed Supabase sign-in links an existing account by email or creates a `brand_owner` account with the existing Self/Personal scope behavior.
- Supabase JWT claims never set an AnaRisk role or organization. The backend verifies the token's signature, issuer, audience, expiry, subject, and authenticated-user role. For first-time linking/provisioning it also asks Supabase Auth for the authoritative confirmed user record. Admin-created accounts are invited through the server-only Supabase secret key; users choose their own password.
- The frontend's Supabase client persists and refreshes its supported session. Protected API calls obtain the current access token and send it as `Authorization: Bearer ...`.

## Environment variables

### Supabase project

Use the Dashboard **Connect** dialog for the Project URL, and **Settings → API Keys** to create/copy a **publishable** key (`sb_publishable_...`) and backend **secret** key (`sb_secret_...`). The secret key is needed only by the protected admin invitation function. Never use it in the browser.

In **Authentication → URL Configuration**:

- Set Site URL to `https://anarisk1-pkvr.vercel.app`.
- Add redirect URLs `https://anarisk1-pkvr.vercel.app/verify-email`, `https://anarisk1-pkvr.vercel.app/reset-password`, and local development URLs `http://localhost:5173/verify-email`, `http://localhost:5173/reset-password`, `http://127.0.0.1:5173/verify-email`, and `http://127.0.0.1:5173/reset-password`.
- Keep email confirmation enabled. Configure SMTP in **Authentication → SMTP Settings** and edit the confirmation, invitation, and recovery templates under **Authentication → Email Templates**. The frontend sends `/verify-email` and `/reset-password` as allowed redirect targets; admin invitations land on the password setup page.

In **Project Settings → Data API**, remove `public` from Exposed Schemas if AnaRisk does not need Supabase's Data API for application tables. The current React app does not read application tables directly; all such reads/writes go through FastAPI. Revision `0011` enables RLS and adds no user-facing policies, so browser Data API access is denied even if `public` remains exposed. If direct browser access is added later, create and test explicit policies first. The Render backend uses the PostgreSQL owner connection for trusted server operations; the existing FastAPI authorization checks remain authoritative.

### Render backend

In **Render → anarisk-api → Environment**, set:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Supabase PostgreSQL connection string. Prefer the Session Pooler connection for a persistent Render service when direct IPv6 connectivity is unavailable. Add `sslmode=require`; keep this value private. |
| `SUPABASE_URL` | Supabase Project URL, e.g. `https://<project-ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase `sb_publishable_...` key. This key is public; it is used as the API key for Auth user verification. |
| `SUPABASE_SECRET_KEY` | Supabase `sb_secret_...` key. Backend only; required for admin invitations. Never add it to Vercel or any `VITE_` variable. |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` |
| `CORS_ORIGINS` | `https://anarisk1-pkvr.vercel.app` (plus any exact custom domain) |
| `FRONTEND_URL` | `https://anarisk1-pkvr.vercel.app` |

Keep the existing `SECRET_KEY` configured because it protects other application features and the legacy local-auth path. The verifier uses Supabase JWKS for ES256/RS256/EdDSA and Auth's `/user` endpoint for legacy HS256 tokens; it does not require the project signing secret. `SUPABASE_SECRET_KEY` is used only by the admin invitation operation; invited users choose their password through the recovery flow.

### Vercel frontend

In **Vercel → Project → Settings → Environment Variables**, set for Production and Preview as appropriate:

| Variable | Value |
| --- | --- |
| `VITE_SUPABASE_URL` | Supabase Project URL |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key (`sb_publishable_...`) |
| `VITE_API_BASE_URL` | Render backend origin, e.g. `https://<your-render-service>.onrender.com` |

The matching placeholders are in `frontend/.env.example` and `backend/.env.example`. Vite embeds `VITE_` values in browser assets, so they must never contain a secret.

## Safe database migration and cutover

The repository cannot access the Supabase dashboard, Render database credentials, or production backups. Do not point the live service at a new empty Supabase database before transferring the current data.

1. Schedule a maintenance window and stop writes to AnaRisk. Preserve the current Render `DATABASE_URL` securely in your password manager or deployment secret store; do not paste it into chat or commit it.
2. Take a fresh custom-format PostgreSQL backup of the current Render database, for example `pg_dump --format=custom --no-owner --no-acl --file anarisk-before-supabase.dump "$DATABASE_URL"`. Protect the dump because it contains production data. Verify it with `pg_restore --list anarisk-before-supabase.dump` and keep a second copy.
3. Create the Supabase project. Create the target schema by restoring the database dump into the new Supabase database, or use a reviewed migration process that restores all application tables, sequences, `alembic_version`, data, constraints, and indexes. Use the Supabase Session Pooler if Render cannot reach the direct database endpoint. Do not run the app's migrations against the source and target interchangeably.
4. Compare table counts and key relationships on the source and target. Check `alembic_version`; it should be `0009` before the application deploy. Verify a restore to a separate scratch database before production cutover. Do not use `scripts/seed.py` against production.
5. Set the Render variables above with the Supabase connection string. The Render Blueprint now declares `DATABASE_URL` as a manually configured value and runs `alembic upgrade head` before deploy. Revision `0010` adds only the Supabase identity-link column/index; `0011` enables RLS without exposing app tables to browser roles.
6. Deploy Render while writes are still paused. Check `/api/v1/ready`, confirm the schema revision is `0011`, and exercise sign-in plus read/write flows with a test user before reopening writes.
7. Configure Vercel variables and Supabase Auth URLs/SMTP, deploy the frontend, then run the verification checklist below.

The application does not dual-write. After cutover, Supabase is the only application database. Keep the original Render database and pre-cutover backup intact until the new deployment and restored data have been accepted.

## First sign-in and roles

Supabase Auth verifies the password and email. On the user's first authenticated API request, FastAPI fetches that user's confirmed record from Supabase Auth and links by `supabase_user_id`. A same-email AnaRisk record keeps its existing role and organization. A new record receives `brand_owner`; admins must assign any other role or organization through the existing admin workflow. User-editable metadata never grants a role. An existing AnaRisk account whose email differs from the confirmed Supabase address requires an administrator to reconcile it before sign-in.

## Verification checklist

1. Sign up with a new test address. Confirm no session is granted before email verification when Supabase email confirmation is enabled.
2. Open the email link in the same browser. Confirm `/verify-email` restores a session and the backend creates a profile with `brand_owner` role and a Personal/Self scope (unless an organization name was entered).
3. Sign out, sign in, reload a protected page, and verify the session restores and protected FastAPI calls include a current bearer token.
4. Request a password reset, open the recovery link, set a new password, and sign in with it.
5. Check that a regular user cannot access another organization and cannot elevate their role by editing browser data. Verify the backend still denies unauthorized role/organization actions.
6. Test existing linked users, admin routes, investigation creation/retrieval, dashboards, alerts, and AI investigation endpoints against the restored data.
7. Confirm Vercel deep links work after refresh, Render `/api/v1/ready` is healthy, and CORS allows only the configured frontend origins.

## Rollback

Keep the original Render database unchanged during the validation window. If the cutover must be reversed, pause writes first. Decide which database contains the accepted post-cutover writes; if Supabase accepted writes, dump and restore those writes to the rollback target before switching the Render `DATABASE_URL` back. Otherwise, switching back to the old Render database would lose writes made after cutover. Restore the pre-cutover backup only into a separate database unless a reviewed recovery plan requires replacing data. Revisions `0010` and `0011` do not delete application data.
