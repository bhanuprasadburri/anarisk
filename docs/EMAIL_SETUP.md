# Email setup — OTP signup verification & password reset

AnaRisk uses real transactional email for two flows:

| Flow | Credential | Lifetime | Storage |
| --- | --- | --- | --- |
| Signup verification | 6-digit OTP (`POST /auth/verify-email`) | `OTP_TTL_MINUTES` (default 10 min), single-use, `OTP_MAX_ATTEMPTS` (default 5) wrong guesses lock the code | Only an HMAC-SHA256 hash keyed with `SECRET_KEY` (`email_verification_tokens.attempts` backs the lockout) |
| Password reset | Opaque link token (`POST /auth/reset-password`) | 30 minutes, single-use | SHA-256 hash only (`password_reset_tokens`) |

Key behaviours (all covered by the test suite):

- Accounts created through public signup are **not activated until the OTP is confirmed** —
  login is rejected with the uniform `401 invalid_credentials`, byte-identical to an unknown
  address (the sign-in screen never reveals whether an account exists).
- **No account enumeration**: register, verify, resend, login and password-reset responses are
  uniform whether an address is unknown, pending, or already verified. Wrong code, expired
  code, locked-out code and unknown addresses all return the same generic 400.
- **Honest delivery**: `email_sent=false` (register/resend) and `status=delivery_failed`
  (register) whenever the provider did not accept the message. A failed send is never
  reported as sent. Password reset in production without a provider fails loudly with 503.
- Resend has a per-email cooldown (`RESEND_VERIFICATION_COOLDOWN_SECONDS`, default 60s) that
  applies to known and unknown addresses alike, plus per-IP rate limits on all auth endpoints.
- Profile email changes (`PATCH /auth/me`) reset verification and send a fresh OTP to the
  new address; the account must re-verify before the next login.

## Providers

`EMAIL_PROVIDER` selects the transport:

| Value | Use | Notes |
| --- | --- | --- |
| `none` | Development without SMTP | Outside production, no email is sent and the API returns a dev-only `dev_otp` (register/resend) plus honest `email_sent=false`. **In production, `none` never returns a code** — reset requests 503, OTP signup reports `delivery_failed`. |
| `resend` | Production (recommended) | Calls the Resend HTTP API. Requires `RESEND_API_KEY` and a **verified** `EMAIL_FROM_ADDRESS` domain. |
| `smtp` | Any SMTP server | Gmail app passwords, Amazon SES, Postmark SMTP, etc. |
| `memory` | Test suite only | In-process capture; asserts run against the real service layer without a network. |

Every send (successful, skipped, or failed) is recorded in `email_delivery_logs` with status
`sent` / `skipped` / `failed` — never with the OTP or token itself.

## Setup: Resend

1. Create an account at <https://resend.com> and verify your sender domain
   (Domains → Add Domain, then add the DNS records Resend shows). Using
   `noreply@yourdomain.com` requires that domain to be verified; unverified domains are
   rejected by the API (HTTP 422).
2. Create an API key: API Keys → Create Key. It starts with `re_`.
3. Configure the backend:

   ```env
   EMAIL_PROVIDER=resend
   RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
   EMAIL_FROM_ADDRESS=noreply@yourdomain.com   # must match the verified domain
   EMAIL_FROM_NAME=AnaRisk
   ```

4. Restart the API and register a test account — the OTP arrives in the recipient inbox
   (check spam). Delivery acceptance is recorded in `email_delivery_logs`.

> Never commit a real API key. `.env` is git-ignored; `.env.example` contains placeholders
> only. If a key has ever been committed or shared, revoke it in the Resend dashboard and
> create a new one.

## Setup: Gmail SMTP (development / small deployments)

1. Enable 2-Step Verification on the Google account (required for app passwords).
2. Create an app password: Google Account → Security → App passwords → generate one for
   "Mail". The 16-character value goes in `SMTP_PASSWORD` (never the account password).
3. Configure the backend:

   ```env
   EMAIL_PROVIDER=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=you@gmail.com
   SMTP_PASSWORD=abcd efgh ijkl mnop     # the 16-character app password
   SMTP_STARTTLS=true
   SMTP_USE_SSL=false
   EMAIL_FROM_ADDRESS=you@gmail.com      # must match the authenticated account
   EMAIL_FROM_NAME=AnaRisk
   ```

   Verified live against `smtp.gmail.com:587` (STARTTLS + app-password AUTH): Gmail
   accepted the message (`email_delivery_logs.status = sent`). Gmail accepts the
   16-character app password with or without the spaces Google displays it with.

## Testing without a real inbox

- **Automated**: the backend suite (330 tests) exercises delivery through the `memory`
  transport — successful send, provider failure, invalid/expired/locked-out/reused OTP,
  cooldown, rate limiting, and no-enumeration assertions — plus an SMTP suite
  (`tests/test_smtp_transport.py`) that asserts the exact Gmail-style conversation
  (EHLO → STARTTLS → EHLO → AUTH → DATA → QUIT), the From header built from
  `EMAIL_FROM_NAME` + `EMAIL_FROM_ADDRESS`, the port-465 SSL variant, signup → verify →
  login through the SMTP path, honest AUTH-failure reporting, and that neither the app
  password nor the OTP ever appears in logs or in the delivery log. Run with:

  ```powershell
  cd backend
  $env:TEST_DATABASE_URL="postgresql+psycopg://nimbus:nimbus_dev_pw@127.0.0.1:5432/nimbus_test"
  .\.venv\Scripts\python.exe -m pytest -q
  ```

- **Manual (dev server)**: start the API with `EMAIL_PROVIDER=none` and `ENVIRONMENT=development`,
  register at the sign-in page, and use the "Development mode … your code is NNNNNN" panel —
  or call the endpoints directly:

  ```powershell
  curl -X POST http://127.0.0.1:8000/api/v1/auth/register -ContentType "application/json" `
    -Body '{"email":"you@example.com","full_name":"You","password":"Passw0rd-123!"}'
  # → 201 with dev_otp (dev only). Then:
  curl -X POST http://127.0.0.1:8000/api/v1/auth/verify-email -ContentType "application/json" `
    -Body '{"email":"you@example.com","code":"<dev_otp>"}'
  ```

- **With a real provider but no inbox**: Resend's sandbox accepts messages sent to its own
  testing address (`delivered@resend.dev`) — useful to confirm authentication, sender
  verification, and API integration end-to-end without a real recipient.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `email_sent=false`, delivery log `failed`, log line `HTTP 422 … testing email address` | Recipient domain not allowed by Resend. Real addresses need a verified sender domain; for sandbox testing use `delivered@resend.dev`. |
| `HTTP 422 … ` from sender side | `EMAIL_FROM_ADDRESS` domain is not verified in the Resend dashboard (or does not match the authenticated account for SMTP). |
| `HTTP 401 API key is invalid` | `RESEND_API_KEY` missing, revoked, or mistyped. |
| Register returns `status=delivery_failed` in development | `EMAIL_PROVIDER=none`: no email is sent by design and a dev code is returned. Configure a provider for real delivery. |
| Register returns `status=delivery_failed` in production | No working provider — configure `resend` or `smtp`. The account exists in an unverified state; the user (or an admin) can retry via resend once delivery works. |
| `503 email_delivery_unavailable` on password reset | Production + `EMAIL_PROVIDER=none`: fails loudly instead of pretending to send. |
| SMTP: log line `SMTP send failed: (535, ... authentication failed)` | `SMTP_USERNAME`/`SMTP_PASSWORD` rejected — use a Google **app password** (16 characters, generated with 2-Step Verification enabled), never the account password. |
| SMTP: log line `SMTP send failed: [Errno ...] Connection refused / timed out` | Wrong `SMTP_HOST`/`SMTP_PORT`, or the network blocks outbound port 587. Port 587 wants `SMTP_STARTTLS=true` + `SMTP_USE_SSL=false`; port 465 wants `SMTP_USE_SSL=true`. |
| SMTP: message accepted (`status=sent`) but not in the inbox | Provider acceptance is not inbox placement — check spam/promotions, and confirm the recipient address is real. Gmail also throttles new/low-reputation senders. |
| Codes expire too quickly in testing | Raise `OTP_TTL_MINUTES` (default 10). Codes are intentionally short-lived. |

## Production checklist

- [ ] `EMAIL_PROVIDER=resend` (or `smtp`) with real credentials — never `none` in production.
- [ ] `ENVIRONMENT=production`, strong `SECRET_KEY` (it keys the OTP HMAC).
- [ ] Verified sender domain; `noreply@` address that actually receives bounces.
- [ ] `OTP_TTL_MINUTES` ≤ 15, `OTP_MAX_ATTEMPTS` ≤ 5, `RESEND_VERIFICATION_COOLDOWN_SECONDS` ≥ 60.
- [ ] `RATE_LIMIT_ENABLED=true` and a reverse proxy that supplies real client IPs.
      (Rate limiting and the resend cooldown are per-process; multi-worker deployments
      should front them with a shared store such as Redis.)
