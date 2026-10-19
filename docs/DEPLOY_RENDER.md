# Deploying AnaRisk to Render + Vercel with Supabase

AnaRisk runs FastAPI on Render, React on Vercel, and uses Supabase for Auth and PostgreSQL. The Render Blueprint (`../render.yaml`) creates the API service; `DATABASE_URL` is configured manually for Supabase after completing the safe cutover procedure.

## Before deployment

Follow [SUPABASE_MIGRATION.md](SUPABASE_MIGRATION.md) first. It includes the backup/restore workflow, exact Supabase, Render, and Vercel variables, email redirect setup, verification checks, and rollback procedure. Do not point the live API at an empty Supabase database; the current Render PostgreSQL database may contain production data.

## Render

Set `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `SUPABASE_JWT_AUDIENCE=authenticated` in **Render → anarisk-api → Environment**. Keep the existing production `SECRET_KEY`, and set `CORS_ORIGINS` and `FRONTEND_URL` to `https://anarisk1-pkvr.vercel.app`. The Blueprint runs `alembic upgrade head` before deploy and checks `/api/v1/ready`, which validates database connectivity and the migration revision.

## Vercel

Set `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and `VITE_API_BASE_URL` in **Vercel → Project → Settings → Environment Variables**. The API base URL is the Render service origin; the frontend appends `/api/v1`. Redeploy after changing build-time Vite variables.

Only Supabase publishable keys belong in Vite variables. Never expose database credentials or a service-role/secret key in frontend variables.

## Readiness and smoke check

```sh
curl -i https://<your-render-service>.onrender.com/api/v1/ready
```

Expect HTTP 200 and `"status":"ready"`. The Render log should report migration revision `0011`. Then test signup, email confirmation, sign-in, session restoration after refresh, password recovery, organization isolation, and representative investigation/AI endpoints as listed in the migration guide.
