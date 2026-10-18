from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    ConflictError, DomainError, ForbiddenError, NotFoundError, ServiceUnavailableError, UnauthorizedError, ValidationFailure,
)
from app.core.security import (
    burn_password_check, create_access_token, hash_password, validate_password_strength, verify_password,
)
from app.models import EmailVerificationToken, Organization, PasswordResetToken, User
from app.models.enums import UserRole
from app.schemas.auth import OrganizationCreate, UpdateMeRequest, UserCreate, UserUpdate
from app.services import audit
from app.services.email import (
    EmailDeliveryError, is_delivery_capable, render_registration_notice_email, render_otp_email, render_reset_email, send_email,
)

log = logging.getLogger(__name__)
INVALID_LOGIN = "Invalid email or password"
RESET_TOKEN_TTL_MINUTES = 30
MAX_PREFERENCES_BYTES = 8192
GENERIC_VERIFY_ERROR = "The code is incorrect or has expired. Request a new code and try again."


def authenticate(db: Session, email: str, password: str) -> tuple[str, int]:
    """Password check + session issue. Logs WHICH gate rejected the attempt (never the password
    or hash) so a production log share pinpoints the failure without exposing credentials."""
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None:
        log.info("login rejected: no account for email=%s", email.strip().lower())
        burn_password_check(password)
        raise UnauthorizedError(INVALID_LOGIN, code="invalid_credentials")
    if not verify_password(password, user.hashed_password):
        log.warning("login rejected: bad password (user_id=%s)", user.id)
        audit.record(db, user, "auth.login_failed", "user", user.id)
        db.commit()
        raise UnauthorizedError(INVALID_LOGIN, code="invalid_credentials")
    if not user.is_active:
        # Same message as a bad password: do not reveal that the account exists but is disabled.
        log.warning("login rejected: account inactive (user_id=%s)", user.id)
        raise UnauthorizedError(INVALID_LOGIN, code="invalid_credentials")
    if user.email_verified_at is None:
        # Only reached AFTER the password checked out, so this never confirms an account to
        # someone who does not already know the credentials. Accounts created through public
        # signup are not activated until their email OTP is confirmed.
        log.info("login blocked: email not verified (user_id=%s)", user.id)
        raise ForbiddenError(
            "Your email address has not been verified yet. Enter the 6-digit code we sent you, "
            "or request a new one from the sign-in page.",
            code="email_not_verified",
        )
    user.last_login_at = datetime.now(UTC)
    audit.record(db, user, "auth.login", "user", user.id)
    db.commit()
    log.info("login succeeded (user_id=%s)", user.id)
    return create_access_token(user.id)


def register_public(db: Session, email: str, full_name: str, password: str) -> dict:
    """Self-registration with email OTP verification (brand_owner, no organization until an
    administrator assigns one; a caller can never choose their own role or organization).

    The account is created UNVERIFIED — it is not activated until the OTP is confirmed.
    The response is deliberately uniform whether or not the address already had an account,
    so public signup never discloses registration state (no account enumeration):

      * new address         -> account created + 6-digit OTP emailed
      * existing, pending   -> a fresh OTP replaces the outstanding one
      * existing, verified  -> a generic "signup attempt" notice (no code) is emailed

    The OTP is echoed only as ``dev_otp`` outside production when no email provider can
    deliver it; it is never logged and never returned in production.
    """
    s = get_settings()
    if not s.allow_public_registration:
        raise ForbiddenError("Public registration is disabled", code="registration_disabled")
    validate_password_strength(password)
    email_n = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_n))
    if user is None:
        candidate = User(email=email_n, full_name=full_name.strip(), hashed_password=hash_password(password), role=UserRole.BRAND_OWNER)
        db.add(candidate)
        try:
            db.flush()
        except IntegrityError:
            # Concurrent signup for the same address: fall back to the generic existing-account path.
            db.rollback()
            user = db.scalar(select(User).where(func.lower(User.email) == email_n))
            if user is None:
                raise ConflictError("Could not create the account right now; please try again", code="registration_conflict")
        else:
            user = candidate
            audit.record(db, user, "auth.register", "user", user.id)
            db.commit()

    dev_otp: str | None = None
    if user.email_verified_at is None:
        # Pending signup: issue a fresh single-use OTP (invalidates any outstanding code).
        code = _issue_otp(db, user)
        email_sent = _send_otp_email(db, user, code)
        if s.environment != "production" and not provider_delivers():
            dev_otp = code
    else:
        # Existing verified account: notice only — no code, nothing the caller can use.
        email_sent = _send_registration_notice(db, user.email, user.full_name, user.id)
    return {
        "status": "verification_required" if email_sent else "delivery_failed",
        "email": email_n,
        "verification_required": True,
        "email_sent": email_sent,
        "dev_otp": dev_otp,
        "dev_only": dev_otp is not None,
    }


def create_user(db: Session, actor: User, data: UserCreate) -> User:
    validate_password_strength(data.password)
    if data.role != UserRole.ADMIN and data.organization_id is None:
        pass  # allowed: such a user has no data access until assigned
    if data.organization_id and db.get(Organization, data.organization_id) is None:
        raise ValidationFailure("organization_id does not exist")
    user = User(
        email=data.email.strip().lower(), full_name=data.full_name.strip(), hashed_password=hash_password(data.password),
        role=data.role, organization_id=data.organization_id,
        email_verified_at=datetime.now(UTC),  # created by an administrator: the address is vouched for
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("An account with this email already exists", code="email_taken")
    audit.record(db, actor, "user.create", "user", user.id, details={"role": data.role.value, "organization_id": str(data.organization_id) if data.organization_id else None})
    db.commit()
    return user


def update_user(db: Session, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    changes: dict = {}
    if data.full_name is not None:
        user.full_name = data.full_name.strip()
        changes["full_name"] = True
    if data.role is not None and data.role != user.role:
        if user.id == actor.id:
            raise ForbiddenError("You cannot change your own role")
        changes["role"] = [user.role.value, data.role.value]
        user.role = data.role
    if data.is_active is not None and data.is_active != user.is_active:
        if user.id == actor.id and not data.is_active:
            raise ForbiddenError("You cannot deactivate your own account")
        changes["is_active"] = data.is_active
        user.is_active = data.is_active
    if data.clear_organization:
        user.organization_id = None
        changes["organization_id"] = None
    elif data.organization_id is not None:
        if db.get(Organization, data.organization_id) is None:
            raise ValidationFailure("organization_id does not exist")
        user.organization_id = data.organization_id
        changes["organization_id"] = str(data.organization_id)
    if data.password:
        validate_password_strength(data.password)
        user.hashed_password = hash_password(data.password)
        changes["password_changed"] = True
    audit.record(db, actor, "user.update", "user", user.id, details=changes, organization_id=user.organization_id)
    db.commit()
    return user


def create_organization(db: Session, actor: User, data: OrganizationCreate) -> Organization:
    org = Organization(name=data.name, slug=data.slug, description=data.description)
    db.add(org)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Organization slug already exists", code="slug_taken")
    audit.record(db, actor, "organization.create", "organization", org.id, organization_id=org.id)
    db.commit()
    return org


# ---------- email verification (OTP) ----------
def provider_delivers() -> bool:
    return is_delivery_capable()


def _otp_hash(user_id: uuid.UUID, code: str) -> str:
    """HMAC-SHA256 of the code keyed with SECRET_KEY. Only this digest is stored: even a
    full database dump cannot be brute-forced offline (1e6 candidates) without the app
    secret, and the digest never equals the code itself."""
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, f"{user_id}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_otp() -> str:
    """Cryptographically secure 6-digit code (secrets module, never `random`)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _issue_otp(db: Session, user: User) -> str:
    """Create a fresh single-use OTP; invalidates any outstanding codes for this user.
    The plaintext code exists only in the return value — never in the DB or logs."""
    s = get_settings()
    code = _generate_otp()
    now = datetime.now(UTC)
    db.execute(update(EmailVerificationToken).where(
        EmailVerificationToken.user_id == user.id, EmailVerificationToken.used_at.is_(None)
    ).values(used_at=now))
    db.add(EmailVerificationToken(
        user_id=user.id, token_hash=_otp_hash(user.id, code),
        expires_at=now + timedelta(minutes=s.otp_ttl_minutes), attempts=0,
    ))
    db.commit()
    return code


def _send_otp_email(db: Session, user: User, code: str) -> bool:
    """Email the OTP. Returns True only when the provider accepted the message.
    The code is never written to logs or to the delivery log."""
    s = get_settings()
    subject, text, html = render_otp_email(user.full_name, code, s.otp_ttl_minutes)
    try:
        row = send_email(
            db, template="email_otp", to=user.email, subject=subject,
            text_body=text, html_body=html, user_id=user.id, commit=True,
        )
        return row is not None and row.status == "sent"
    except EmailDeliveryError as exc:
        # The API must not lie: report email_sent=False without leaking the code.
        log.error("OTP email for %s could not be delivered: %s", user.email, exc)
        return False


def _send_registration_notice(db: Session, to: str, name: str | None, user_id: uuid.UUID | None) -> bool:
    """Generic notice for signup/resend attempts on an address without a pending signup.
    Contains no code and reveals nothing about account state."""
    subject, text, html = render_registration_notice_email(name, to)
    try:
        row = send_email(
            db, template="registration_notice", to=to, subject=subject,
            text_body=text, html_body=html, user_id=user_id, commit=True,
        )
        return row is not None and row.status == "sent"
    except EmailDeliveryError as exc:
        log.error("Registration-notice email to %s could not be delivered: %s", to, exc)
        return False


# Per-email resend throttle (in-process, same caveat as the rate limiter: multi-worker
# deployments should back it with a shared store). Keys are SHA-256 digests of the
# address, and the cooldown is checked BEFORE any account lookup and marked for every
# address alike — known and unknown addresses behave identically, so the cooldown state
# itself never discloses whether an account exists.
_cooldown_lock = threading.Lock()
_resend_cooldowns: dict[str, float] = {}  # sha256(email) -> monotonic deadline


def reset_resend_cooldowns() -> None:
    """Clear the in-memory resend cooldowns (used between tests)."""
    with _cooldown_lock:
        _resend_cooldowns.clear()


def _cooldown_remaining(email_n: str) -> float:
    s = get_settings()
    if s.resend_verification_cooldown_seconds <= 0:
        return 0.0
    key = hashlib.sha256(email_n.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _cooldown_lock:
        deadline = _resend_cooldowns.get(key)
        if deadline is None:
            return 0.0
        if deadline <= now:
            del _resend_cooldowns[key]
            return 0.0
        return deadline - now


def _mark_cooldown(email_n: str) -> None:
    s = get_settings()
    if s.resend_verification_cooldown_seconds <= 0:
        return
    key = hashlib.sha256(email_n.encode("utf-8")).hexdigest()
    deadline = time.monotonic() + s.resend_verification_cooldown_seconds
    with _cooldown_lock:
        if len(_resend_cooldowns) > 10_000:  # opportunistic cleanup, no background task
            now = time.monotonic()
            for k, d in list(_resend_cooldowns.items()):
                if d <= now:
                    del _resend_cooldowns[k]
        _resend_cooldowns[key] = deadline


def verify_email(db: Session, email: str, code: str) -> User:
    """Confirm the 6-digit OTP for a pending signup and activate the account.

    Single-use (consumed atomically), attempt-limited per code, TTL-bound, and row-locked
    so two concurrent verifications can never both consume the same code. Every failure —
    unknown address, wrong code, expired, locked out — returns the same generic 400, so
    this endpoint never discloses whether an address is registered."""
    s = get_settings()
    invalid = DomainError(GENERIC_VERIFY_ERROR, code="invalid_or_expired_otp", status_code=400)
    email_n = email.strip().lower()
    now = datetime.now(UTC)
    # Lock the user row first (always user -> token: consistent order avoids deadlocks).
    # `of=User` locks only the users table — the eager-joined organization may be nullable.
    user = db.scalar(select(User).where(func.lower(User.email) == email_n).with_for_update(of=User))
    if user is None:
        # Equalise work/timing for unknown addresses, then fail identically.
        secrets.compare_digest(_otp_hash(uuid.uuid4(), code), "0" * 64)
        raise invalid
    row = db.scalar(select(EmailVerificationToken).where(
        EmailVerificationToken.user_id == user.id, EmailVerificationToken.used_at.is_(None)
    ).order_by(EmailVerificationToken.created_at.desc()).with_for_update())
    code_ok = row is not None and secrets.compare_digest(row.token_hash, _otp_hash(user.id, code))
    if row is None or row.expires_at <= now or row.attempts >= s.otp_max_attempts or not code_ok:
        if row is not None and row.expires_at > now and not code_ok:
            # Wrong code on a live credential: count the attempt and burn the code at the limit.
            row.attempts += 1
            if row.attempts >= s.otp_max_attempts:
                row.used_at = now
            audit.record(db, user, "auth.email_verify_failed", "user", user.id,
                         details={"attempts": row.attempts})
        db.commit()  # persists the attempt counter even though we raise below
        raise invalid
    # Success: consume the code (single-use) and activate the account in one transaction.
    row.used_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now
    db.execute(update(EmailVerificationToken).where(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None),
        EmailVerificationToken.id != row.id,
    ).values(used_at=now))
    audit.record(db, user, "auth.email_verified", "user", user.id)
    db.commit()
    return user


def resend_verification(db: Session, email: str) -> dict:
    """Resend the signup OTP — or a generic notice for addresses without a pending signup.

    Uniform by design: the same shape and status come back whether the address is
    unknown, already verified, or pending, so this endpoint cannot be used to enumerate
    accounts. A per-email cooldown (checked before any lookup, marked for every address)
    throttles abuse. A delivery failure is reported honestly as email_sent=False — the
    caller never sees a success claim for a message that did not leave the process.
    Rate-limited by the router."""
    s = get_settings()
    email_n = email.strip().lower()
    remaining = _cooldown_remaining(email_n)
    if remaining > 0:
        return {"status": "cooldown", "retry_after_seconds": max(1, int(remaining)),
                "email_sent": False, "dev_otp": None, "dev_only": False}
    user = db.scalar(select(User).where(func.lower(User.email) == email_n))
    dev_otp: str | None = None
    if user is None or not user.is_active or user.email_verified_at is not None:
        # Unknown / inactive / already verified -> identical generic notice, no code.
        email_sent = _send_registration_notice(
            db, email_n, user.full_name if user else None, user.id if user else None)
    else:
        code = _issue_otp(db, user)
        email_sent = _send_otp_email(db, user, code)
        if s.environment != "production" and not provider_delivers():
            dev_otp = code
    _mark_cooldown(email_n)
    out: dict = {"status": "accepted", "email_sent": email_sent,
                 "retry_after_seconds": max(0, s.resend_verification_cooldown_seconds),
                 "dev_otp": dev_otp, "dev_only": dev_otp is not None}
    return out


# ---------- password recovery / self-service profile ----------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def forgot_password(db: Session, email: str) -> dict:
    """Always returns {"status": "sent"} - unknown addresses behave exactly like known ones (no enumeration).
    Sends a real, single-use reset email when a provider is configured. In development without a
    provider the token is also returned as `dev_reset_token` so the flow works end to end.
    A provider delivery failure is reported honestly as 503 (it is never pretended to be sent)."""
    s = get_settings()
    if s.environment == "production" and not provider_delivers():
        raise ServiceUnavailableError(
            "Password-reset emails cannot be delivered right now (no email provider is configured). "
            "Contact your administrator.", code="email_delivery_unavailable",
        )
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None or not user.is_active:
        log.info("Password reset requested for an unknown or inactive address - ignored (no user enumeration)")
        return {"status": "sent"}
    token = secrets.token_urlsafe(32)  # 32 random bytes, stored ONLY as a SHA-256 hash
    db.add(PasswordResetToken(
        user_id=user.id, token_hash=_token_hash(token),
        expires_at=datetime.now(UTC) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
    ))
    audit.record(db, user, "auth.password_reset_request", "user", user.id)
    db.commit()
    link = f"{s.frontend_url.rstrip('/')}/reset-password?token={token}"
    subject, text, html = render_reset_email(user.full_name, link, RESET_TOKEN_TTL_MINUTES)
    try:
        send_email(
            db, template="password_reset", to=user.email, subject=subject,
            text_body=text, html_body=html, user_id=user.id, commit=True,
        )
    except EmailDeliveryError as exc:
        log.error("Password-reset email for %s could not be delivered (token not logged): %s", user.email, exc)
        raise ServiceUnavailableError(
            "The password-reset email could not be delivered. Please try again later.",
            code="email_delivery_failed",
        )
    if s.environment == "production":
        # No secrets in production logs: the message states that a link was created without printing it.
        log.info("Password reset requested for %s: a 30-minute reset link was emailed (token not logged in production)",
                 user.email)
        return {"status": "sent"}
    if provider_delivers():
        # A real provider sent the link; do not echo the token (same as production behaviour).
        log.info("Password reset link emailed to %s (token not echoed: an email provider is configured)", user.email)
        return {"status": "sent"}
    log.info("PASSWORD RESET for %s (expires in %s minutes) -> %s",
             user.email, RESET_TOKEN_TTL_MINUTES, link)
    return {"status": "sent", "dev_reset_token": token, "dev_only": True}


def reset_password(db: Session, token: str, new_password: str) -> User:
    invalid = DomainError("This reset link is invalid or has expired; request a new one",
                          code="invalid_or_expired_token", status_code=400)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _token_hash(token)))
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise invalid
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise invalid
    validate_password_strength(new_password)
    user.hashed_password = hash_password(new_password)
    row.used_at = now
    db.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None), PasswordResetToken.id != row.id
    ).values(used_at=now))  # one click invalidates every other outstanding link
    audit.record(db, user, "auth.password_reset", "user", user.id)
    db.commit()
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> User:
    if not verify_password(current_password, user.hashed_password):
        raise DomainError("Current password is incorrect", code="invalid_current_password", status_code=400)
    validate_password_strength(new_password)
    user.hashed_password = hash_password(new_password)
    db.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
    ).values(used_at=datetime.now(UTC)))  # a successful change invalidates pending reset links
    audit.record(db, user, "auth.password_change", "user", user.id)
    db.commit()
    return user


def update_own_profile(db: Session, user: User, data: UpdateMeRequest) -> User:
    changes: dict = {}
    new_email = None
    if data.full_name is not None and data.full_name.strip() != user.full_name:
        user.full_name = data.full_name.strip()
        changes["full_name"] = True
    if data.email is not None:
        email = data.email.strip().lower()
        if email != user.email:
            taken = db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != user.id))
            if taken:
                raise ConflictError("An account with this email already exists", code="email_taken")
            user.email = email
            # A changed address is unverified until its owner confirms the new OTP.
            user.email_verified_at = None
            new_email = email
            changes["email"] = True
    if data.preferences is not None:
        try:
            if len(json.dumps(data.preferences)) > MAX_PREFERENCES_BYTES:
                raise ValueError("too large")
        except (TypeError, ValueError):
            raise ValidationFailure(f"preferences must be JSON-serialisable and smaller than {MAX_PREFERENCES_BYTES} bytes")
        user.preferences = data.preferences
        changes["preferences"] = sorted(str(k) for k in data.preferences)
    if not changes:
        return user
    audit.record(db, user, "user.update_self", "user", user.id, details=changes)
    db.commit()
    if new_email is not None:
        # Send the OTP for the new address (dev flows fetch it via resend-verification).
        code = _issue_otp(db, user)
        _send_otp_email(db, user, code)
    return user
