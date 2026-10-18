"""Transactional email delivery.

Providers are configured through environment variables (see Settings):

- ``smtp``   - any SMTP relay (Amazon SES, Postfix, Gmail app password, Mailgun SMTP, ...).
- ``resend`` - the Resend HTTP API.
- ``memory`` - captures messages in process memory; used by tests and local development.
- ``none``   - no provider. Reset/verification flows fall back to the documented
               ``dev_*_token`` response field in non-production, and fail loudly in production.

Delivery outcomes are recorded honestly in the ``email_delivery_logs`` table. A provider
failure is raised as :class:`EmailDeliveryError` so callers can never pretend an email
was sent when it was not.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailDeliveryLog

log = logging.getLogger(__name__)


class EmailTransportError(Exception):
    """Raised by a transport when the provider rejects or cannot send a message."""


class EmailDeliveryError(Exception):
    """Raised when an email could not be delivered after retries."""


@dataclass
class OutboundEmail:
    to: str
    subject: str
    text_body: str
    html_body: str
    template: str
    user_id: Any = None


class BaseTransport:
    name = "base"

    def send(self, email: OutboundEmail) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class MemoryTransport(BaseTransport):
    """Captures messages in a process-local list. Used by tests (and nothing else)."""

    name = "memory"
    outbox: list[OutboundEmail] = []

    def send(self, email: OutboundEmail) -> None:
        MemoryTransport.outbox.append(email)

    @classmethod
    def clear(cls) -> None:
        cls.outbox.clear()


class SMTPTransport(BaseTransport):
    name = "smtp"

    def send(self, email: OutboundEmail) -> None:
        s = get_settings()
        msg = MimeMessage()
        msg["From"] = formataddr((s.email_from_name, s.email_from_address))
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg.set_content(email.text_body)
        msg.add_alternative(email.html_body, subtype="html")
        try:
            if s.smtp_use_ssl:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    s.smtp_host, s.smtp_port, timeout=s.email_timeout_seconds, context=ssl.create_default_context()
                )
            else:
                client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.email_timeout_seconds)
            try:
                client.ehlo()
                if s.smtp_starttls and not s.smtp_use_ssl:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if s.smtp_username:
                    client.login(s.smtp_username, s.smtp_password)
                client.send_message(msg)
            finally:
                client.quit()
        except (smtplib.SMTPException, OSError) as exc:  # SMTPAuthenticationError etc.
            raise EmailTransportError(f"SMTP send failed: {exc}") from exc


class ResendTransport(BaseTransport):
    name = "resend"

    def send(self, email: OutboundEmail) -> None:
        s = get_settings()
        try:
            resp = httpx.post(
                f"{s.resend_api_base_url.rstrip('/')}/emails",
                headers={"Authorization": f"Bearer {s.resend_api_key}"},
                json={
                    "from": formataddr((s.email_from_name, s.email_from_address)),
                    "to": [email.to],
                    "subject": email.subject,
                    "text": email.text_body,
                    "html": email.html_body,
                },
                timeout=s.email_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise EmailTransportError(f"Resend request failed: {exc}") from exc
        if resp.status_code >= 400:
            # Never echo the API key; the response body is safe (provider error message).
            raise EmailTransportError(f"Resend returned HTTP {resp.status_code}: {resp.text[:500]}")


_TRANSPORTS: dict[str, type[BaseTransport]] = {
    "smtp": SMTPTransport,
    "resend": ResendTransport,
    "memory": MemoryTransport,
}
_transport_cache: dict[str, BaseTransport] = {}


def get_transport() -> BaseTransport | None:
    """Return the configured transport, or None when EMAIL_PROVIDER=none."""
    s = get_settings()
    if s.email_provider == "none":
        return None
    if s.email_provider not in _transport_cache:
        factory = _TRANSPORTS.get(s.email_provider)
        if factory is None:
            raise EmailTransportError(f"Unknown EMAIL_PROVIDER '{s.email_provider}'")
        _transport_cache[s.email_provider] = factory()
    return _transport_cache[s.email_provider]


def provider_configured() -> bool:
    return get_settings().email_provider != "none"


def is_delivery_capable() -> bool:
    """True when an email can actually leave this process right now."""
    s = get_settings()
    if s.email_provider == "smtp":
        return bool(s.smtp_host)
    if s.email_provider == "resend":
        return bool(s.resend_api_key)
    return s.email_provider == "memory"


def send_email(
    db: Session,
    *,
    template: str,
    to: str,
    subject: str,
    text_body: str,
    html_body: str,
    user_id: Any = None,
    commit: bool = False,
) -> EmailDeliveryLog | None:
    """Send one email and record the honest outcome.

    Returns the persisted delivery log. Raises :class:`EmailDeliveryError` when no email
    left this process. With EMAIL_PROVIDER=none in non-production the row is recorded as
    ``skipped`` (dev token flows still work); in production that combination is an error.
    """
    s = get_settings()
    transport = get_transport()
    email = OutboundEmail(to=to, subject=subject, text_body=text_body, html_body=html_body, template=template, user_id=user_id)
    row = EmailDeliveryLog(
        user_id=user_id, template=template, recipient=to, subject=subject,
        provider=s.email_provider, status="failed", error=None,
    )
    if transport is None or not is_delivery_capable():
        if s.environment == "production":
            row.error = "no email provider configured (EMAIL_PROVIDER=none or missing credentials)"
            db.add(row)
            db.commit()
            raise EmailDeliveryError(row.error)
        row.status = "skipped"
        row.error = "no email provider configured - development fallback applies"
        db.add(row)
        if commit:
            db.commit()
        else:
            db.flush()
        return row

    attempts = 1 + max(0, s.email_max_retries)
    last_error: str | None = None
    for attempt in range(attempts):
        try:
            transport.send(email)
            last_error = None
            break
        except EmailTransportError as exc:
            last_error = str(exc)
            log.warning("Email send attempt %d/%d failed (%s): %s", attempt + 1, attempts, template, exc)
    if last_error is not None:
        row.status = "failed"
        row.error = last_error
        db.add(row)
        if commit:
            db.commit()
        else:
            db.flush()
        raise EmailDeliveryError(f"Email delivery failed via provider '{s.email_provider}': {last_error}")
    row.status = "sent"
    row.error = None
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return row


# --------------------------------------------------------------------------- templates

_BASE_STYLE = (
    "body{margin:0;padding:32px;background:#111318;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;}"
    ".card{max-width:520px;margin:0 auto;background:#1A1D24;border:1px solid #353B47;border-radius:12px;padding:32px;}"
    "h1{font-size:20px;color:#F5F3EE;margin:0 0 12px;}"
    "p{color:#A6ACB8;font-size:14px;line-height:1.6;margin:0 0 16px;}"
    ".btn{display:inline-block;background:#D5FF6E;color:#111318;font-weight:600;text-decoration:none;"
    "padding:12px 20px;border-radius:8px;font-size:14px;}"
    ".link{color:#82D8F4;font-size:12px;word-break:break-all;}"
    ".foot{color:#6B7280;font-size:12px;margin-top:24px;border-top:1px solid #353B47;padding-top:16px;}"
)


def _wrap(title: str, paragraphs: list[str], button_label: str | None = None, button_url: str | None = None) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    btn = f'<p><a class="btn" href="{button_url}">{button_label}</a></p>' if button_label and button_url else ""
    url = f'<p class="link">If the button does not work, open this link:<br>{button_url}</p>' if button_url else ""
    return (
        f"<!doctype html><html><body><div class='card'><h1>{title}</h1>{body}{btn}{url}"
        f"<p class='foot'>AnaRisk - Digital Risk Protection. If you did not create this account you can ignore this email.</p>"
        f"</div></body></html>"
    )


def render_otp_email(name: str, code: str, ttl_minutes: int) -> tuple[str, str]:
    """Verification email carrying the 6-digit signup OTP. The code is the ONLY secret in
    the message; callers must never log it."""
    subject = "Your AnaRisk verification code"
    text = (
        f"Hello {name},\n\nYour AnaRisk verification code is:\n\n    {code}\n\n"
        f"This code expires in {ttl_minutes} minutes and can be used once. "
        f"It only confirms your email address — we will never ask you to forward it.\n\n"
        "If you did not create this account you can ignore this email.\n"
    )
    html = _wrap(
        "Verify your email",
        [f"Hello {name},", "Your verification code is:",
         f"<strong style='display:inline-block;font-size:28px;letter-spacing:8px;color:#F5F3EE'>{code}</strong>",
         f"This code expires in {ttl_minutes} minutes and can be used once."],
    )
    return subject, text, html


def render_registration_notice_email(name: str | None, attempted: str) -> tuple[str, str]:
    """Sent when a signup is attempted for an address that already has an account.
    Deliberately reveals nothing about account state to the caller; the notice itself
    only goes to the address owner."""
    who = f"Hello {name}," if name else "Hello,"
    subject = "Signup attempt for your AnaRisk account"
    text = (
        f"{who}\n\nA signup was recently attempted for {attempted} on AnaRisk.\n"
        "If this was you, the account already exists — just sign in (or reset your password).\n"
        "If it was not you, no action is needed; the attempt did not create anything.\n"
    )
    html = _wrap("Signup attempt", [who, f"A signup was recently attempted for <strong>{attempted}</strong> on AnaRisk.",
                                    "If this was you, just sign in. If not, you can ignore this message."])
    return subject, text, html


def render_reset_email(name: str, link: str, ttl_minutes: int) -> tuple[str, str]:
    subject = "Reset your password - AnaRisk"
    text = (
        f"Hello {name},\n\nA password reset was requested for your account.\n"
        f"This link expires in {ttl_minutes} minutes and can be used once.\n\n{link}\n\n"
        "If you did not request this, you can safely ignore this email.\n"
    )
    html = _wrap(
        "Reset your password",
        [f"Hello {name},", "A password reset was requested for your account.",
         f"This link expires in {ttl_minutes} minutes and can be used once."],
        "Reset password", link,
    )
    return subject, text, html


def render_generic_email(name: str, title: str, body: str) -> tuple[str, str]:
    text = f"Hello {name},\n\n{body}\n"
    html = _wrap(title, [f"Hello {name},", body])
    return title, text, html
