from __future__ import annotations

import uuid

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.context import request_ip
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token:
        raise UnauthorizedError("Not authenticated", code="not_authenticated")
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
