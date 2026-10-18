from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.deps import capture_ip
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers

_ROOT = Path(__file__).resolve().parents[1]

log = logging.getLogger("app")


@lru_cache
def expected_head() -> str | None:
    """Alembic head revision shipped with this code."""
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _startup_database_probe() -> None:
    """Verify at boot that the database is reachable AND migrated.

    The liveness endpoint intentionally never touches the database, so without this probe a
    broken DATABASE_URL or a missing migration still yields a "successful" deploy whose every
    DB-backed request is a 500. Failures are logged loudly, with an actionable hint and never
    with credentials; the process keeps running so /api/v1/ready reports 503 and requests get
    honest error bodies instead of a crash-loop.
    """
    try:
        from sqlalchemy import text

        from app.db.session import get_sessionmaker

        with get_sessionmaker()() as probe:
            probe.execute(text("SELECT 1"))
    except Exception:
        log.exception(
            "DATABASE PROBE FAILED at startup — every DB-backed request will return HTTP 500 "
            "until this is fixed (check DATABASE_URL format/credentials/network; provider URLs "
            "like postgres:// are normalised automatically, so the remaining causes are wrong "
            "credentials, unreachable host, or TLS policy). /api/v1/ready reports 503."
        )
        return
    try:
        from sqlalchemy import text

        from app.db.session import get_sessionmaker

        with get_sessionmaker()() as probe:
            revision = probe.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        log.exception(
            "MIGRATIONS NOT APPLIED: the alembic_version table is missing or unreadable — "
            "DB-backed requests will fail. Run: alembic upgrade head")
        return
    expected = expected_head()
    if revision != expected:
        log.error(
            "MIGRATIONS NOT APPLIED: database is at revision %r but this build expects %r — "
            "DB-backed requests will fail. Run: alembic upgrade head", revision, expected,
        )
    else:
        log.info("database probe ok (migration revision %s)", revision)


def create_app() -> FastAPI:
    s = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from urllib.parse import urlparse

        from app.services import scheduler

        # Effective configuration snapshot — safe to print: the database URL is reduced to
        # host/port/name (credentials never appear) and no secret values are logged. Makes
        # production log shares diagnosable at a glance.
        db = urlparse(s.database_url)
        logging.getLogger("app").info(
            "config: environment=%s email_provider=%s ai_provider=%s cors_origins=%s "
            "db=%s:%s%s rate_limit=%s bcrypt_rounds=%s",
            s.environment, s.email_provider, s.ai_provider, s.cors_origins,
            db.hostname, db.port, db.path, s.rate_limit_enabled, s.bcrypt_rounds,
        )
        _startup_database_probe()
        scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(
        title=s.app_name, version=s.app_version, debug=s.debug,
        description=("Backend for AnaRisk - Digital Risk Protection. Detection scores are **heuristic and unvalidated**; "
                     "investigators must confirm findings before any enforcement. Data provenance (collected/manual/synthetic) is tracked everywhere."),
        docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json", dependencies=[Depends(capture_ip)],
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    install_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/api/v1/health", tags=["Health"], summary="Liveness")
    def health():
        return {"status": "ok", "version": s.app_version}

    @app.get("/api/v1/ready", tags=["Health"], summary="Readiness (checks the database and that migrations are applied)")
    def ready(response: Response):
        # The session is created INSIDE the handler: a broken DATABASE_URL (engine creation
        # failure) must surface here as an honest 503 with a server-side traceback, not as an
        # unhandled dependency crash that the global handler flattens into a bare 500.
        db = None
        try:
            from app.db.session import get_sessionmaker

            db = get_sessionmaker()()
            db.execute(text("SELECT 1"))
            rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:
            log.exception("Readiness check failed (database unreachable or engine could not be created)")
            response.status_code = 503
            return {"status": "unavailable", "database": "unreachable or not migrated (run: alembic upgrade head)"}
        finally:
            if db is not None:
                db.close()
        if rev != expected_head():
            response.status_code = 503
            return {"status": "unavailable", "database": "schema out of date", "migration_revision": rev, "expected_revision": expected_head(),
                    "hint": "run: alembic upgrade head"}
        return {"status": "ready", "database": "ok", "migration_revision": rev}

    return app


app = create_app()
