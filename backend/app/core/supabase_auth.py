"""Verification helpers for Supabase user access tokens.

Asymmetric signing keys are verified locally from Supabase's project JWKS. Legacy HS256
tokens are validated by Supabase Auth's /user endpoint (the recommended shared-secret
path) because the project signing secret must not be copied to application services.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlparse
import uuid

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.core.config import get_settings
from app.core.errors import ConflictError, ServiceUnavailableError, UnauthorizedError


def _issuer() -> str:
    return f"{get_settings().supabase_url.rstrip('/')}/auth/v1"


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=600, timeout=5)


def _validate_claims(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if payload.get("iss") != _issuer():
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    aud = payload.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if settings.supabase_jwt_audience not in audiences:
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    try:
        uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        raise UnauthorizedError("Could not validate credentials", code="invalid_token") from None
    if payload.get("role") != "authenticated" or payload.get("is_anonymous") is not False:
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    if not isinstance(payload.get("email"), str) or not payload["email"].strip():
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    return payload


def verify_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.supabase_auth_enabled:
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    parsed = urlparse(settings.supabase_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ServiceUnavailableError("Supabase Auth is not configured with a valid HTTPS URL")

    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm == "HS256":
            # Supabase recommends validating shared-secret tokens with Auth itself. Its
            # response confirms the signature; PyJWT still checks expiry and we validate
            # issuer/audience before any claim is used.
            response = httpx.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "Authorization": f"Bearer {token}",
                },
                timeout=5.0,
            )
            if response.status_code in (401, 403):
                raise UnauthorizedError("Could not validate credentials", code="invalid_token")
            if response.status_code != 200:
                raise ServiceUnavailableError("Supabase Auth token verification is temporarily unavailable")
            payload = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "require": ["exp", "iat", "sub", "iss", "aud", "role", "is_anonymous"],
                },
                algorithms=["HS256"],
                audience=None,
                issuer=None,
            )
        elif algorithm in {"ES256", "RS256", "EdDSA"}:
            jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
            signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
            if signing_key.algorithm_name != algorithm:
                raise UnauthorizedError("Could not validate credentials", code="invalid_token")
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=settings.supabase_jwt_audience,
                issuer=_issuer(),
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        else:
            raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    except UnauthorizedError:
        raise
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, PyJWKClientError, ValueError, TypeError):
        raise UnauthorizedError("Could not validate credentials", code="invalid_token") from None
    except httpx.TimeoutException:
        raise ServiceUnavailableError("Supabase Auth token verification timed out") from None
    except httpx.RequestError:
        raise ServiceUnavailableError("Supabase Auth token verification is temporarily unavailable") from None
    return _validate_claims(payload)


def get_confirmed_user(token: str) -> dict[str, Any]:
    """Fetch Auth's authoritative user record before linking/provisioning a profile."""
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=5.0,
        )
    except httpx.TimeoutException:
        raise ServiceUnavailableError("Supabase Auth user lookup timed out") from None
    except httpx.RequestError:
        raise ServiceUnavailableError("Supabase Auth user lookup is temporarily unavailable") from None
    if response.status_code in (401, 403):
        raise UnauthorizedError("Could not validate credentials", code="invalid_token")
    if response.status_code != 200:
        raise ServiceUnavailableError("Supabase Auth user lookup is temporarily unavailable")
    try:
        user = response.json()
    except ValueError:
        raise ServiceUnavailableError("Supabase Auth returned an invalid user response") from None
    if not user.get("email") or not (user.get("email_confirmed_at") or user.get("confirmed_at")):
        raise UnauthorizedError("Confirm your email before using AnaRisk", code="email_not_confirmed")
    return user


def invite_user(email: str, full_name: str) -> uuid.UUID:
    """Send a Supabase invitation from the trusted backend for an admin-created AnaRisk user."""
    settings = get_settings()
    if not settings.supabase_secret_key:
        raise ServiceUnavailableError("Admin invitations require SUPABASE_SECRET_KEY on the backend")
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/invite",
            params={"redirect_to": f"{settings.frontend_url.rstrip('/')}/reset-password"},
            headers={
                "apikey": settings.supabase_secret_key,
            },
            json={"email": email, "data": {"full_name": full_name}},
            timeout=8.0,
        )
    except httpx.TimeoutException:
        raise ServiceUnavailableError("Supabase invitation request timed out") from None
    except httpx.RequestError:
        raise ServiceUnavailableError("Supabase invitation service is temporarily unavailable") from None
    if response.status_code in (400, 409, 422):
        raise ConflictError("Supabase could not invite this email address", code="email_taken")
    if response.status_code != 200:
        raise ServiceUnavailableError("Supabase invitation service is temporarily unavailable")
    try:
        user = response.json()
        return uuid.UUID(str(user["id"]))
    except (ValueError, KeyError, TypeError):
        raise ServiceUnavailableError("Supabase returned an invalid invitation response") from None
