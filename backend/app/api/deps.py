from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.context import request_ip
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.core.supabase_auth import get_confirmed_user, verify_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def _supabase_user(token: str, payload: dict, db: Session) -> User:
    """Resolve a verified Supabase identity to the trusted AnaRisk authorization record."""
    try:
        subject = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        raise UnauthorizedError("Could not validate credentials", code="invalid_token") from None

    user = db.scalar(select(User).where(User.supabase_user_id == subject))
    if user is not None:
        if not user.is_active:
            raise UnauthorizedError("Could not validate credentials", code="invalid_token")
        if user.email_verified_at is None:
            auth_user = get_confirmed_user(token)
            confirmed_id = str(auth_user.get("id", ""))
            confirmed_email = str(auth_user.get("email", "")).strip().lower()
            token_email = str(payload.get("email", "")).strip().lower()
            if confirmed_id != str(subject) or confirmed_email != token_email:
                raise UnauthorizedError("Could not validate credentials", code="invalid_token")
            user.email_verified_at = datetime.now(UTC)
            db.commit()
        token_email = str(payload.get("email", "")).strip().lower()
        if token_email and token_email != user.email.lower():
            auth_user = get_confirmed_user(token)
            confirmed_id = str(auth_user.get("id", ""))
            confirmed_email = str(auth_user.get("email", "")).strip().lower()
            if confirmed_id != str(subject) or confirmed_email != token_email:
                raise UnauthorizedError("Could not validate credentials", code="invalid_token")
            collision = db.scalar(select(User.id).where(func.lower(User.email) == token_email, User.id != user.id))
            if collision:
                raise UnauthorizedError(
                    "The confirmed email is already linked to another AnaRisk account",
                    code="account_link_required",
                )
            user.email = token_email
            user.email_verified_at = datetime.now(UTC)
            db.commit()
        return user

    # Only first-time linking/provisioning needs the Auth user endpoint. Subsequent API
    # requests rely on the already verified JWT and the server-controlled active flag.
    auth_user = get_confirmed_user(token)
    try:
        auth_subject = uuid.UUID(str(auth_user["id"]))
    except (KeyError, ValueError, TypeError):
        raise UnauthorizedError("Could not validate credentials", code="invalid_token") from None
    if subject != auth_subject:
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")

    email = str(auth_user["email"]).strip().lower()
    if email != str(payload.get("email", "")).strip().lower():
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is not None:
        # Linking by email is permitted only after Auth has confirmed this exact address.
        user.supabase_user_id = subject
        user.email_verified_at = user.email_verified_at or datetime.now(UTC)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            user = db.scalar(select(User).where(User.supabase_user_id == subject))
            if user is None:
                raise UnauthorizedError(
                    "This email already has an AnaRisk account. Contact an administrator to link it.",
                    code="account_link_required",
                ) from None
        if not user.is_active:
            raise UnauthorizedError("Could not validate credentials", code="invalid_token")
        return user

    # Authorization is server-controlled. Signup metadata is used only for display/scope
    # naming; neither role nor organization ID can be supplied by the browser.
    metadata = auth_user.get("user_metadata") or {}
    full_name = str(metadata.get("full_name") or metadata.get("name") or email.partition("@")[0])[:200].strip()
    organization_name = str(metadata.get("organization_name") or "").strip()[:200] or None
    from app.core.security import hash_password
    from app.services import users as users_svc

    user = User(
        supabase_user_id=subject,
        email=email,
        full_name=full_name or email,
        # Supabase is the only holder of the new account password. Keep the legacy column
        # populated for schema compatibility with old records and admin-created accounts.
        hashed_password=hash_password(secrets.token_urlsafe(48)),
        role=UserRole.BRAND_OWNER,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.flush()
        users_svc._ensure_account_scope(db, user, organization_name)
        db.commit()
    except IntegrityError:
        db.rollback()
        user = db.scalar(select(User).where(User.supabase_user_id == subject))
        if user is None:
            raise UnauthorizedError(
                "This email already has an AnaRisk account. Contact an administrator to link it.",
                code="account_link_required",
            ) from None
    return user


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token:
        raise UnauthorizedError("Not authenticated", code="not_authenticated")
    from app.core.config import get_settings
    if get_settings().supabase_auth_enabled:
        payload = verify_access_token(token)
        return _supabase_user(token, payload, db)
    payload = decode_access_token(token)
    try:
        uid = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    user = db.get(User, uid)
    if user is None or not user.is_active:  # deactivation takes effect immediately, even for unexpired tokens
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    return user


def require_permission(permission: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise ForbiddenError(f"Your role does not permit this action ({permission})")
        return user

    return dep


def capture_ip(request: Request) -> None:
    from app.core.config import get_settings
    from app.core.context import client_ip

    request_ip.set(
        client_ip(
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
            get_settings().trust_proxy_headers,
        )
    )


class Pagination:
    """Validated pagination params (documented in OpenAPI): page >= 1, 1 <= page_size <= 100."""

    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        self.page = page
        self.page_size = page_size
