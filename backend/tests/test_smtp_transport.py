"""SMTP transport configuration + honest SMTP delivery reporting.

smtplib is replaced with in-process fakes, so the full SMTP conversation
(connect -> EHLO -> STARTTLS -> EHLO -> AUTH -> DATA -> QUIT) is asserted
deterministically without touching a real mail server. Live Gmail acceptance is
verified separately (see docs/EMAIL_SETUP.md) - here we prove the client code
does exactly what the configuration says.

Guarantees under test:
  * EMAIL_PROVIDER=smtp reads host/port/starttls and the From header uses
    EMAIL_FROM_NAME + EMAIL_FROM_ADDRESS;
  * signup emails the OTP through SMTP, keeps the account pending, and blocks
    login until the emailed code is confirmed;
  * an SMTP rejection is reported as a failure - never as a sent email;
  * the app password and OTP codes never appear in logs or in the delivery log.
"""
from __future__ import annotations

import logging
import smtplib
import ssl

import pytest
from sqlalchemy import select

import app.services.email as email_mod
from app.models import EmailDeliveryLog
from tests.conftest import PASSWORD

# Stand-in shaped like a real Gmail app password ("xxxx xxxx xxxx xxxx").
APP_PASSWORD = "abcd efgh ijkl mnop"

_connections: list["_BaseFakeSMTP"] = []


class _BaseFakeSMTP:
    kind = "plain"

    def __init__(self, host, port, timeout=None, **kwargs):
        self.host, self.port, self.timeout, self.kwargs = host, port, timeout, kwargs
        self.calls: list = []
        self.msg = None
        _connections.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append(("starttls", context))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.msg = msg
        self.calls.append("send_message")

    def quit(self):
        self.calls.append("quit")


class _FakeSMTP(_BaseFakeSMTP):
    kind = "plain"


class _FakeSMTPSSL(_BaseFakeSMTP):
    kind = "ssl"


class _FakeAuthFailSMTP(_BaseFakeSMTP):
    def login(self, user, password):
        self.calls.append(("login", user, password))
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Application-specific password required")


@pytest.fixture(autouse=True)
def _clean_connections():
    _connections.clear()
    yield
    _connections.clear()


@pytest.fixture
def smtp_settings(settings, monkeypatch):
    """EMAIL_PROVIDER=smtp with Gmail-shaped settings, pinned hermetically
    (values come from the fixture, never from the developer's .env)."""
    for attr, value in {
        "email_provider": "smtp",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "sender@example.test",
        "smtp_password": APP_PASSWORD,
        "smtp_starttls": True,
        "smtp_use_ssl": False,
        "email_from_address": "sender@example.test",
        "email_from_name": "AnaRisk Test Suite",
    }.items():
        monkeypatch.setattr(settings, attr, value)
    return settings


def _otp_from_message(msg) -> str:
    body = msg.get_body(preferencelist=("plain",)).get_content()
    codes = [w for w in body.replace("\n", " ").split() if len(w) == 6 and w.isdigit()]
    assert len(codes) == 1, f"expected exactly one 6-digit OTP in the email, got: {body!r}"
    return codes[0]


# ---------------------------------------------------------------- transport configuration

def test_smtp_starttls_auth_and_from_header(smtp_settings, monkeypatch, db):
    """Port 587 STARTTLS path: EHLO -> STARTTLS -> EHLO -> AUTH -> DATA -> QUIT,
    authenticated with the configured credentials, From built from name + address."""
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    row = email_mod.send_email(
        db, template="email_otp", to="user@example.test",
        subject="Your AnaRisk verification code",
        text_body="Your code is 123456.", html_body="<p>Your code is 123456.</p>",
        commit=True,
    )
    assert row.status == "sent" and row.error is None
    assert len(_connections) == 1
    conn = _connections[0]
    assert conn.kind == "plain"
    assert (conn.host, conn.port) == ("smtp.gmail.com", 587)
    assert conn.timeout == smtp_settings.email_timeout_seconds
    steps = [c if isinstance(c, str) else c[0] for c in conn.calls]
    assert steps == ["ehlo", "starttls", "ehlo", "login", "send_message", "quit"]
    starttls = next(c for c in conn.calls if isinstance(c, tuple) and c[0] == "starttls")
    assert isinstance(starttls[1], ssl.SSLContext), "STARTTLS must run with a default SSL context"
    login = next(c for c in conn.calls if isinstance(c, tuple) and c[0] == "login")
    assert login[1] == "sender@example.test"
    assert login[2] == APP_PASSWORD
    # EMAIL_FROM_NAME + EMAIL_FROM_ADDRESS compose the From header
    assert conn.msg["From"] == "AnaRisk Test Suite <sender@example.test>"
    assert conn.msg["To"] == "user@example.test"
    assert conn.msg["Subject"] == "Your AnaRisk verification code"


def test_smtp_port465_style_uses_ssl_and_skips_starttls(smtp_settings, monkeypatch, db):
    """SMTP_USE_SSL=true uses SMTP_SSL directly (no STARTTLS after implicit TLS)."""
    monkeypatch.setattr(smtp_settings, "smtp_use_ssl", True)  # starttls stays true: SSL wins
    monkeypatch.setattr(email_mod.smtplib, "SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)  # must NOT be selected
    row = email_mod.send_email(
        db, template="email_otp", to="user@example.test",
        subject="s", text_body="t 111111", html_body="<p>t</p>",
        commit=True,
    )
    assert row.status == "sent"
    assert len(_connections) == 1
    conn = _connections[0]
    assert conn.kind == "ssl"
    assert not any(isinstance(c, tuple) and c[0] == "starttls" for c in conn.calls)
    assert any(isinstance(c, tuple) and c[0] == "login" for c in conn.calls)


def test_smtp_not_configured_reports_not_capable_not_sent(settings, monkeypatch, db):
    """EMAIL_PROVIDER=smtp with an empty SMTP_HOST never claims delivery (dev: skipped,
    and is_delivery_capable() agrees)."""
    monkeypatch.setattr(settings, "email_provider", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "")
    row = email_mod.send_email(
        db, template="email_otp", to="user@example.test",
        subject="s", text_body="t", html_body="<p>t</p>",
        commit=True,
    )
    assert row.status == "skipped" and not email_mod.is_delivery_capable()


# ---------------------------------------------------------------- signup -> verify over SMTP

def test_smtp_signup_sends_otp_and_blocks_login_until_verified(smtp_settings, monkeypatch, f, db, caplog):
    """Full chain through the SMTP path: register -> OTP emailed -> login 403 ->
    verify with the code from the email -> login 200. Secrets stay out of the logs."""
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    with caplog.at_level(logging.DEBUG):
        r = f.client.post("/api/v1/auth/register", json={
            "email": "smtp-chain@example.com", "full_name": "SMTP Chain", "password": PASSWORD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "verification_required" and body["email_sent"] is True
    assert body["dev_otp"] is None, "a provider is configured: the code must not be echoed"
    assert len(_connections) == 1
    otp = _otp_from_message(_connections[0].msg)
    # the OTP never reaches any application log, and the app password never reaches any log
    app_log_text = "\n".join(rec.getMessage() for rec in caplog.records if rec.name.startswith("app."))
    assert otp not in app_log_text
    assert APP_PASSWORD not in caplog.text
    # the account is pending and login stays closed (uniform rejection)
    denied = f.client.post("/api/v1/auth/login", json={"email": "smtp-chain@example.com", "password": PASSWORD})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "invalid_credentials"
    log_row = db.scalar(select(EmailDeliveryLog).where(EmailDeliveryLog.template == "email_otp"))
    assert log_row is not None and log_row.status == "sent" and log_row.error is None
    # verify with the code that arrived in the email, then login succeeds
    ok = f.client.post("/api/v1/auth/verify-email", json={"email": "smtp-chain@example.com", "code": otp})
    assert ok.status_code == 200, ok.text
    allowed = f.client.post("/api/v1/auth/login", json={"email": "smtp-chain@example.com", "password": PASSWORD})
    assert allowed.status_code == 200, allowed.text


# ---------------------------------------------------------------- failure honesty

def test_smtp_auth_failure_is_reported_never_claimed(smtp_settings, monkeypatch, f, db, caplog):
    """A Gmail AUTH rejection (e.g. bad app password) surfaces as email_sent=False /
    status=delivery_failed, a failed delivery-log row, and an unchanged login gate."""
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeAuthFailSMTP)
    with caplog.at_level(logging.DEBUG):
        r = f.client.post("/api/v1/auth/register", json={
            "email": "smtp-fail@example.com", "full_name": "SMTP Fail", "password": PASSWORD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_sent"] is False, "provider rejected the message: never claim it was sent"
    assert body["status"] == "delivery_failed"
    assert body["dev_otp"] is None, "provider configured but failed: honest failure, no code echo"
    log_row = db.scalar(select(EmailDeliveryLog).where(EmailDeliveryLog.template == "email_otp"))
    assert log_row is not None and log_row.status == "failed"
    assert log_row.error and "SMTP send failed" in log_row.error
    assert APP_PASSWORD not in log_row.error, "secrets must never be persisted"
    assert APP_PASSWORD not in caplog.text, "secrets must never be logged"
    # the account is still pending: login stays blocked (uniform rejection)
    denied = f.client.post("/api/v1/auth/login", json={"email": "smtp-fail@example.com", "password": PASSWORD})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "invalid_credentials"
    # resend endpoint reports the SMTP failure honestly too (and starts the cooldown)
    rr = f.client.post("/api/v1/auth/resend-verification", json={"email": "smtp-fail@example.com"})
    assert rr.status_code == 200
    assert rr.json()["status"] == "accepted"
    assert rr.json()["email_sent"] is False, "resend must not claim delivery that did not happen"
    assert rr.json()["dev_otp"] is None
