# URL model shadow staging

This is a separate, manual staging path. It does not change the production `render.yaml`, URL-fetch setting, model threshold, API findings, or risk scoring. Shadow output is stored only as `input_summary.url_model_shadow`. It is diagnostic metadata and must never be interpreted as a confirmed threat.

## Current blocker

The selected artifact is `ml-training/models/url-char-tfidf-v0.1.0-research.joblib` (SHA-256 `d4ff1b4ea161edcdeee78c6be1956b51f87ef8a23d5b59600a602d0033b4c005`). The training data provenance and license/rights for distributing the derived artifact have not been established. The artifact is deliberately absent from the staging build context, image and Git. Do not pass `-RightsReviewed` until the data and derived-model usage rights have been reviewed and recorded. This local scaffolding does not establish that staging deployment is authorized or configured.

## Build context (after rights review)

From the repository root in PowerShell, after recording approval for this exact artifact:

```powershell
./backend/scripts/staging/prepare_staging_context.ps1 -ExpectedArtifactSha256 'd4ff1b4ea161edcdeee78c6be1956b51f87ef8a23d5b59600a602d0033b4c005' -RightsReviewed
  -ExpectedArtifactSha256 'd4ff1b4ea161edcdeee78c6be1956b51f87ef8a23d5b59600a602d0033b4c005' `
  -RightsReviewed
```

The script verifies the artifact hash and copies only the backend runtime, minimal pinned inference dependencies, validator, and selected URL artifact to a unique temporary directory. It prints the context path; from that directory run:

```powershell
docker build -f Dockerfile.staging -t anarisk-url-shadow:staging .
```

The Dockerfile fixes the artifact destination, makes the artifact read-only, runs as a non-root user, installs `requirements-url-staging.txt`, and checks exact ML dependency versions, model metadata, threshold and SHA-256 before starting the API. The startup check rejects missing or mismatched artifacts, missing/incompatible ML packages, and non-shadow or URL-fetch-enabled configuration. No user-provided artifact path is accepted. The Render staging blueprint is manual-only (`autoDeployTrigger: "off"`) and has no pre-deploy migration. Render cannot use the temporary local build context; configuring its private build source/artifact delivery remains a separate rights-gated step. Do not sync the blueprint or build/push an image until that is resolved.

## Staging-only configuration

Supply these in a staging service only; do not copy production values. Never commit secrets. `DATABASE_URL` must target a separate staging Supabase project/database with its schema already migrated through an approved staging-only procedure. No migration runs on container startup or in the staging blueprint.

| Variable | Value or requirement |
| --- | --- |
| `ENVIRONMENT` | `staging` |
| `DATABASE_URL` | Staging-only Supabase Postgres URI; never production |
| `SUPABASE_URL` | Staging Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Staging project publishable key |
| `SUPABASE_SECRET_KEY` | Staging project server-only key |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` |
| `SECRET_KEY` | Unique staging secret, at least 32 characters |
| `CORS_ORIGINS` | Exact staging frontend origin(s), comma-separated |
| `FRONTEND_URL` | Staging frontend origin |
| `URL_MODEL_SHADOW_ENABLED` | `true` |
| `URL_MODEL_ARTIFACT_PATH` | `/app/var/models/url-char-tfidf-v0.1.0-research.joblib` |
| `URL_MODEL_ARTIFACT_SHA256` | Exact reviewed digest shown above |
| `URL_FETCH_ENABLED` | `false` |
| `RUN_MIGRATIONS` | `false` |
| `EMAIL_PROVIDER`, `AI_PROVIDER` | `none` for this isolated smoke test |
| `MONITORING_WORKER_ENABLED` | `false` |
| `ALLOW_PUBLIC_REGISTRATION` | `false`; create a staging test account through the approved staging auth process |

The `render.staging.yaml` has no production credentials and marks credentials as dashboard-supplied (`sync: false`). No dashboard values, service, database, or deployment have been configured by this work.

## Smoke test and measurements

Before testing, confirm the service is the staging service, its database is the staging database, the build log includes the model checksum validation message, `URL_FETCH_ENABLED=false`, and the model switch is `true`. Confirm the staging schema is current; readiness will fail if it is not. Authenticate with a staging-only account. Example PowerShell (substitute the staging URL and securely obtain a staging token):

```powershell
$base = 'https://<staging-api-host>'
$headers = @{ Authorization = "Bearer $env:ANARISK_STAGING_TOKEN" }
Invoke-RestMethod "$base/api/v1/ready"
$body = @{ url = 'https://example.com/' } | ConvertTo-Json
$cold = Measure-Command { $first = Invoke-RestMethod "$base/api/v1/tools/url/analyze" -Method Post -Headers $headers -ContentType 'application/json' -Body $body }
$warm = 1..20 | ForEach-Object {
  Measure-Command { $response = Invoke-RestMethod "$base/api/v1/tools/url/analyze" -Method Post -Headers $headers -ContentType 'application/json' -Body $body }
}
[pscustomobject]@{ ColdMs = $cold.TotalMilliseconds; WarmMedianMs = ($warm.TotalMilliseconds | Sort-Object)[9]; ShadowStatus = $response.input_summary.url_model_shadow.status }
```

Record API latency separately from the model’s in-process latency; current telemetry does not expose per-model timings. For a local container, collect memory while exercising it with `docker stats anarisk-url-shadow-staging`. On Render, use the staging service’s metrics/logs. Record idle RSS, peak RSS, first-request latency, and warm median/p95 across repeated requests. Do not send actual user URLs or known malicious URLs for this basic smoke test. Verify that all non-shadow response fields match with shadow enabled and disabled, and that URL fetching remains off.

## Remaining staging work

1. Resolve and document the dataset and derived-artifact license/provenance review.
2. Once approved, prepare and inspect the checksum-gated image context; do not put the artifact in Git.
3. Arrange an authorized private artifact/build path for Render (the local temporary context is not accessible to Render), and configure a separate staging service manually with `render.staging.yaml` only after reviewing its plan and isolation.
4. Provision staging-only Supabase/Auth and frontend origins; manually ensure the staging schema is current. Do not point this service at production.
5. Execute the smoke test and resource measurements, then review results before any later deployment decision.
