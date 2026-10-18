"""Domain exceptions and consistent error responses.

All errors are returned as: {"error": {"code": str, "message": str, "details": [...]|null}}
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException  # base class: also covers router-level 404/405

log = logging.getLogger(__name__)


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details=None, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ValidationFailure(DomainError):
    status_code = 422
    code = "validation_error"


class UnauthorizedError(DomainError):
    status_code = 401
    code = "unauthorized"


class ServiceUnavailableError(DomainError):
    status_code = 503
    code = "service_unavailable"


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 429: "rate_limited"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(_body("validation_error", "Request validation failed", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")  # no request bodies/credentials are logged
        return JSONResponse(_body("internal_error", "Internal server error"), status_code=500)
