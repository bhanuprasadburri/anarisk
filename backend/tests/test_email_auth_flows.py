"""Email OTP verification + delivery honesty + reset flow (real email authentication phase 2).

Uses EMAIL_PROVIDER=memory (in-process capture transport) so delivery is exercised for real
through the service layer without touching an external SMTP service, and EMAIL_PROVIDER=none
for the documented dev-token fallback.

Covered: successful delivery, invalid OTP, expiration, reuse, attempt lockout, resend
cooldown + uniformity (no enumeration), delivery-provider failure honesty, rate limiting,
hash-only storage, login gating until verified.
"""
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.rate_limit import reset_rate_limits
from app.models import EmailDeliveryLog, EmailVerificationToken, User
from app.models.enums import UserRole
from app.services.email import EmailTransportError, MemoryTransport
from tests.conftest import PASSWORD


@pytest.fixture(autouse=True)
def _clear_outbox():
    MemoryTransport.clear()
    yield
    MemoryTransport.clear()


def _register(f, email, name="New Bie", password=PASSWORD):
    return f.client.post("/api/v1/auth/register", json={
        "email": email, "full_name": name, "password": password})


# ---------------------------------------------------------------- registration + delivery

def test_register_dev_mode_no_provider_is_honest_and_unverified(f, db):
    r = _register(f, "newbie@example.com")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "delivery_failed"          # nothing left the process: no success claim
    assert body["email_sent"] is False
    assert body["verification_required"] is True
    assert body["dev_otp"] and len(body["dev_otp"]) == 6 and body["dev_otp"].isdigit()  # dev-only fallback
    assert body["dev_only"] is True
    # account exists but is NOT activated
    u = db.scalar(select(User).where(User.email == "newbie@example.com"))
    assert u is not None and u.email_verified_at is None
    # delivery was honestly recorded as skipped, not sent
    log = db.scalar(select(EmailDeliveryLog).where(EmailDeliveryLog.template == "email_otp"))
    assert log is not None and log.status == "skipped"
    # login is blocked until the OTP is confirmed
    denied = f.client.post("/api/v1/auth/login", json={"email": "newbie@example.com", "password": PASSWORD})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "email_not_verified"


def test_register_with_memory_provider_sends_real_otp_email(f, db, settings):
    settings.email_provider = "memory"
    try:
        r = _register(f, "real-send@example.com", name="Real Send")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "verification_required" and body["email_sent"] is True
        assert body["dev_otp"] is None  # a provider was configured: no code echo
        assert len(MemoryTransport.outbox) == 1
        msg = MemoryTransport.outbox[0]
        assert msg.template == "email_otp"
        # the email carries a 6-digit code (no link flow)
        code = [w for w in msg.text_body.replace("\n", " ").split() if len(w) == 6 and w.isdigit()]
        assert len(code) == 1, f"expected one 6-digit OTP in the email, got: {msg.text_body!r}"
        log = db.scalar(select(EmailDeliveryLog).where(EmailDeliveryLog.template == "email_otp"))
        assert log is not None and log.status == "sent"
    finally:
        settings.email_provider = "none"


def test_register_delivery_failure_never_claims_sent(f, db, settings, monkeypatch):
    settings.email_provider = "memory"
    try:
        def boom(self, email):
            raise EmailTransportError("simulated provider outage")
        monkeypatch.setattr(MemoryTransport, "send", boom)
        r = _register(f, "outage@example.com")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["email_sent"] is False and body["status"] == "delivery_failed"
        assert body["dev_otp"] is None  # provider configured but failed: honest failure, no echo
        log = db.scalar(select(EmailDeliveryLog).where(EmailDeliveryLog.template == "email_otp"))
        assert log is not None and log.status == "failed"
    finally:
        settings.email_provider = "none"


def test_register_is_uniform_and_prevents_duplicate_accounts(f, db):
    r1 = _register(f, "dup@example.com", name="First Try")
    assert r1.status_code == 201
    otp1 = r1.json()["dev_otp"]
    # same address again (pending): uniform 201, still ONE account, fresh code invalidates the old one
    r2 = _register(f, "DUP@example.com", name="Second Try")
    assert r2.status_code == 201
    body2 = r2.json()
    assert set(body2.keys()) == set(r1.json().keys())  # identical response shape
    assert body2["dev_otp"] and body2["dev_otp"] != otp1
    users = db.scalars(select(User).where(User.email == "dup@example.com")).all()
    assert len(users) == 1
    # the superseded code no longer works, the fresh one does
    bad = f.client.post("/api/v1/auth/verify-email", json={"email": "dup@example.com", "code": otp1})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_or_expired_otp"
    ok = f.client.post("/api/v1/auth/verify-email", json={"email": "dup@example.com", "code": body2["dev_otp"]})
    assert ok.status_code == 200, ok.text


def test_register_existing_verified_account_gets_notice_not_code(f, db, settings):
    settings.email_provider = "memory"
    try:
        u = f.user(UserRole.INVESTIGATOR, f.org("Org N"))  # already verified (factory)
        r = _register(f, u.email, name="Impostor")
        assert r.status_code == 201
        body = r.json()
        assert set(body.keys()) == set(_register_shape_keys()), "response shape must stay uniform"
        assert body["dev_otp"] is None            # no code for an already-verified address
        assert body["email_sent"] is True         # the notice went out
        assert len(MemoryTransport.outbox) == 1
        msg = MemoryTransport.outbox[0]
        assert msg.template == "registration_notice"
        assert not any(w.isdigit() and len(w) == 6 for w in msg.text_body.split()), "notice must contain no OTP"
        # still exactly one account, password untouched
        assert db.scalars(select(User).where(User.email == u.email)).all().__len__() == 1
    finally:
        settings.email_provider = "none"


def _register_shape_keys():
    return {"status", "email", "verification_required", "email_sent", "dev_otp", "dev_only"}


# ---------------------------------------------------------------- verify: happy path, reuse, expiry, attempts

def test_verify_happy_path_activates_and_allows_login(f, db):
    r = _register(f, "verifyme@example.com")
    code = r.json()["dev_otp"]
    ok = f.client.post("/api/v1/auth/verify-email", json={"email": "verifyme@example.com", "code": code})
    assert ok.status_code == 200, ok.text
    assert ok.json()["email_verified_at"] is not None
    login = f.client.post("/api/v1/auth/login", json={"email": "verifyme@example.com", "password": PASSWORD})
    assert login.status_code == 200, login.text
    # single use: the same code cannot verify twice (e.g. a second tab)
    again = f.client.post("/api/v1/auth/verify-email", json={"email": "verifyme@example.com", "code": code})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_or_expired_otp"


def test_verify_rejects_wrong_code_and_counts_attempts(f, db, settings):
    code = _register(f, "brute@example.com").json()["dev_otp"]
    wrong = "000000" if code != "000000" else "000001"
    r = f.client.post("/api/v1/auth/verify-email", json={"email": "brute@example.com", "code": wrong})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_or_expired_otp"
    row = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.used_at.is_(None)))
    assert row is not None and row.attempts == 1
    # account must still be unverified
    u = db.scalar(select(User).where(User.email == "brute@example.com"))
    assert u.email_verified_at is None
    # after otp_max_attempts wrong codes the credential is burned — even the right one fails
    for _ in range(settings.otp_max_attempts - 1):
        f.client.post("/api/v1/auth/verify-email", json={"email": "brute@example.com", "code": wrong})
    db.expire_all()
    final = f.client.post("/api/v1/auth/verify-email", json={"email": "brute@example.com", "code": code})
    assert final.status_code == 400, "locked-out code must not accept the correct OTP afterwards"


def test_verify_rejects_expired_code(f, db):
    code = _register(f, "slow@example.com").json()["dev_otp"]
    row = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.used_at.is_(None)))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    r = f.client.post("/api/v1/auth/verify-email", json={"email": "slow@example.com", "code": code})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_or_expired_otp"
    u = db.scalar(select(User).where(User.email == "slow@example.com"))
    assert u.email_verified_at is None  # expiry never activates the account


def test_verify_unknown_address_is_indistinguishable(f):
    # generic failure for an address with no account — byte-identical to a wrong-code failure
    unknown = f.client.post("/api/v1/auth/verify-email",
                            json={"email": "ghost-no-account@example.com", "code": "123456"})
    _register(f, "real-pending@example.com")
    wrong = f.client.post("/api/v1/auth/verify-email",
                          json={"email": "real-pending@example.com", "code": "654321"})
    assert unknown.status_code == 400 and wrong.status_code == 400
    assert json.loads(unknown.text) == json.loads(wrong.text), "responses must be identical (no enumeration)"


def test_verify_otp_stored_only_as_hash(f, db):
    code = _register(f, "hash@example.com").json()["dev_otp"]
    row = db.scalar(select(EmailVerificationToken))
    assert row is not None
    assert row.token_hash != code and len(row.token_hash) == 64
    assert code not in row.token_hash
    # hash is keyed HMAC, not a bare digest of the 6 digits
    assert row.token_hash != hashlib.sha256(code.encode()).hexdigest()


def test_verify_endpoint_rate_limited(f, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    reset_rate_limits()  # start from a clean window inside this test as well
    _register(f, "rate@example.com")  # register bucket: 5/min, one used
    hit = lambda: f.client.post("/api/v1/auth/verify-email", json={"email": "rate@example.com", "code": "000000"})
    codes = [hit().status_code for _ in range(settings.login_rate_limit_per_minute)]
    assert all(c == 400 for c in codes), f"first {settings.login_rate_limit_per_minute} attempts are plain failures: {codes}"
    limited = hit()
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------- resend: uniformity + cooldown

def test_resend_pending_returns_code_then_cooldown(f, settings):
    _register(f, "waiter@example.com")
    r = f.client.post("/api/v1/auth/resend-verification", json={"email": "waiter@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["dev_otp"] and len(body["dev_otp"]) == 6  # dev fallback (no provider)
    assert body["retry_after_seconds"] == settings.resend_verification_cooldown_seconds
    # immediately again: throttled — no new code, explicit retry hint
    r2 = f.client.post("/api/v1/auth/resend-verification", json={"email": "waiter@example.com"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "cooldown" and r2.json()["retry_after_seconds"] >= 1
    assert r2.json()["dev_otp"] is None
    # cooldown of 0 disables throttling (used by tests that must resend freely)
    settings.resend_verification_cooldown_seconds = 0
    try:
        r3 = f.client.post("/api/v1/auth/resend-verification", json={"email": "waiter@example.com"})
        assert r3.json()["status"] == "accepted"
    finally:
        settings.resend_verification_cooldown_seconds = 60


def test_resend_unknown_address_behaves_like_known_no_enumeration(f, settings):
    # unknown: notice, no code — same statuses as the pending path
    r = f.client.post("/api/v1/auth/resend-verification", json={"email": "ghost@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted" and body["dev_otp"] is None
    assert body["retry_after_seconds"] == settings.resend_verification_cooldown_seconds
    # and the cooldown applies to unknown addresses too (uniform behaviour)
    r2 = f.client.post("/api/v1/auth/resend-verification", json={"email": "ghost@example.com"})
    assert r2.json()["status"] == "cooldown"
    # already verified -> also notice-only, never a code
    u = f.user(UserRole.INVESTIGATOR, f.org("Org R"))
    settings.resend_verification_cooldown_seconds = 0
    try:
        r3 = f.client.post("/api/v1/auth/resend-verification", json={"email": u.email})
        assert r3.json()["status"] == "accepted" and r3.json()["dev_otp"] is None
    finally:
        settings.resend_verification_cooldown_seconds = 60


def test_resend_with_memory_provider_sends_notice_for_unknown(f, settings):
    settings.email_provider = "memory"
    try:
        r = f.client.post("/api/v1/auth/resend-verification", json={"email": "no-such-user@example.com"})
        assert r.json()["email_sent"] is True and r.json()["dev_otp"] is None
        assert len(MemoryTransport.outbox) == 1
        assert MemoryTransport.outbox[0].template == "registration_notice"
    finally:
        settings.email_provider = "none"


def test_resend_delivery_failure_is_reported_not_claimed(f, settings, monkeypatch):
    settings.email_provider = "memory"
    try:
        def boom(self, email):
            raise EmailTransportError("simulated provider outage")
        monkeypatch.setattr(MemoryTransport, "send", boom)
        r = f.client.post("/api/v1/auth/resend-verification", json={"email": "anyone@example.com"})
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"
        assert r.json()["email_sent"] is False, "a failed send must never be reported as sent"
    finally:
        settings.email_provider = "none"


# ---------------------------------------------------------------- login gating

def test_login_blocked_until_otp_verified_then_allowed(f):
    _register(f, "gate@example.com", name="Gate Ed")
    denied = f.client.post("/api/v1/auth/login", json={"email": "gate@example.com", "password": PASSWORD})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "email_not_verified"
    # wrong password still fails generically (no verification hint without credentials)
    badpw = f.client.post("/api/v1/auth/login", json={"email": "gate@example.com", "password": "Wrong-Passw0rd!"})
    assert badpw.status_code == 401 and badpw.json()["error"]["code"] == "invalid_credentials"
    code = f.client.post("/api/v1/auth/resend-verification", json={"email": "gate@example.com"}).json()["dev_otp"]
    f.client.post("/api/v1/auth/verify-email", json={"email": "gate@example.com", "code": code})
    ok = f.client.post("/api/v1/auth/login", json={"email": "gate@example.com", "password": PASSWORD})
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------- password reset (unchanged flow)

def test_forgot_password_sends_real_email_and_reset_works(f, db, settings):
    settings.email_provider = "memory"
    try:
        u = f.user(UserRole.INVESTIGATOR, f.org("Org X"))
        r = f.client.post("/api/v1/auth/forgot-password", json={"email": u.email})
        assert r.status_code == 200 and not r.json().get("dev_reset_token")
        assert len(MemoryTransport.outbox) == 1 and "reset-password?token=" in MemoryTransport.outbox[0].text_body
        token = MemoryTransport.outbox[0].text_body.split("reset-password?token=")[1].split()[0]
        ok = f.client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "Brand-N3w-Passw0rd!"})
        assert ok.status_code == 200, ok.text
        # reuse must fail
        again = f.client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "Brand-N3w-Passw0rd!"})
        assert again.status_code == 400
        # new password works
        login = f.client.post("/api/v1/auth/login", json={"email": u.email, "password": "Brand-N3w-Passw0rd!"})
        assert login.status_code == 200
    finally:
        settings.email_provider = "none"


def test_forgot_password_fails_loudly_in_production_without_provider(f, db, settings, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    u = f.user(UserRole.INVESTIGATOR, f.org("Org Y"))
    r = f.client.post("/api/v1/auth/forgot-password", json={"email": u.email})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "email_delivery_unavailable"
