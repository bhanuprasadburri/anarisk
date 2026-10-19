"""Production-configuration and deployment-portability regression tests.

These lock down the root cause of the Render incident: a provider-style DATABASE_URL
(``postgres://`` / ``postgresql://`` without a driver) crashed engine creation or the first
connection, so every DB-backed endpoint returned HTTP 500 while the DB-less ``/health``
check kept passing ("deploy succeeded, login 500").

Covered here:
* URL normalisation for every scheme Render/Heroku hand out (idempotent, credentials intact)
* Settings apply the normalisation to DATABASE_URL / TEST_DATABASE_URL
* a real login succeeds through an engine built from a provider-style URL
* /api/v1/ready reports 503 (not 500) when the engine cannot even be created
* the startup probe logs actionable failures instead of raising
* X-Forwarded-For based client IPs so rate limits are not shared across all proxy users
* the seed script refuses to truncate a production database
"""
from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.url import normalize_database_url
from app.models.enums import UserRole
from tests.conftest import PASSWORD, _TEST_URL, _db_is_available


# --------------------------------------------------------------------------- normalisation

def test_normalize_legacy_provider_schemes():
    """postgres:// (Render/Heroku classic) and bare postgresql:// must become psycopg 3 URLs."""
    assert normalize_database_url("postgres://user:pw@db.example.com:5432/nimbus") == \
        "postgresql+psycopg://user:pw@db.example.com:5432/nimbus"
    assert normalize_database_url("postgresql://user:pw@db.example.com:5432/nimbus") == \
        "postgresql+psycopg://user:pw@db.example.com:5432/nimbus"
    assert normalize_database_url("postgresql+psycopg2://user:pw@h:5432/db") == \
        "postgresql+psycopg://user:pw@h:5432/db"
    # credentials, port, database and query string are byte-identical after the scheme
    src = "postgres://user:p%40ss@db.example.com:5432/nimbus?sslmode=prefer&connect_timeout=5"
    out = normalize_database_url(src)
    assert out.startswith("postgresql+psycopg://user:p%40ss@db.example.com:5432/nimbus?")
    assert "sslmode=prefer" in out and "connect_timeout=5" in out


def test_normalize_is_idempotent_and_leaves_other_dialects_alone():
    canonical = "postgresql+psycopg://user:pw@127.0.0.1:5432/nimbus"
    assert normalize_database_url(canonical) == canonical
    assert normalize_database_url(normalize_database_url(canonical)) == canonical
    assert normalize_database_url("sqlite:///./local.db") == "sqlite:///./local.db"
    assert normalize_database_url("sqlite+aiosqlite:///./local.db") == "sqlite+aiosqlite:///./local.db"
    assert normalize_database_url("") == ""
    assert normalize_database_url(None) is None


def test_normalize_adds_tls_for_providers_that_require_it():
    render = normalize_database_url("postgresql://user:pw@db-abc123.render.com:5432/nimbus")
    assert render.startswith("postgresql+psycopg://user:pw@db-abc123.render.com:5432/nimbus")
    assert "sslmode=require" in render
    # an operator-provided sslmode always wins
    keep = normalize_database_url("postgres://u:p@db-abc123.render.com:5432/d?sslmode=verify-full")
    assert "sslmode=verify-full" in keep and "require" not in keep
    # non-Render hosts are not touched
    plain = normalize_database_url("postgres://u:p@db.example.com:5432/d")
    assert "sslmode" not in plain
    # Supabase direct and pooled endpoints require TLS too.
    assert "sslmode=require" in normalize_database_url("postgres://u:p@db.project-ref.supabase.co:5432/postgres")
    assert "sslmode=require" in normalize_database_url("postgres://u:p@aws-0.pooler.supabase.com:5432/postgres")


def test_settings_database_url_is_normalised():
    from app.core.config import Settings

    s = Settings(database_url="postgres://user:pw@db.example.com:5432/nimbus")
    assert s.database_url.startswith("postgresql+psycopg://user:pw@db.example.com:5432/nimbus")
    t = Settings(test_database_url="postgresql://user:pw@db.example.com:5432/nimbus_test")
    assert t.test_database_url.startswith("postgresql+psycopg://")


def test_engine_created_from_provider_url_connects():
    """The exact production failure: create_engine('postgres://…') used to raise
    NoSuchModuleError before a single query ran."""
    if not _db_is_available():
        pytest.skip("Test database not reachable")
    provider_style = re.sub(r"^postgresql(\+\w+)?://", "postgres://", _TEST_URL)
    engine = create_engine(normalize_database_url(provider_style), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


def test_real_login_through_provider_style_url(f):
    """Password verification + audit + JWT issuance against an engine built from the URL
    shape providers publish — the path that returned HTTP 500 on Render."""
    if not _db_is_available():
        pytest.skip("Test database not reachable")
    u = f.user(UserRole.INVESTIGATOR, f.org())
    provider_style = re.sub(r"^postgresql(\+\w+)?://", "postgres://", _TEST_URL)
    engine = create_engine(normalize_database_url(provider_style), pool_pre_ping=True)
    session = sessionmaker(bind=engine)()
    try:
        from app.services import users as users_svc

        token, expires = users_svc.authenticate(session, u.email, PASSWORD)
        assert token and expires > 0
        with pytest.raises(Exception) as bad:
            users_svc.authenticate(session, u.email, "Wrong-Passw0rd!")
        assert getattr(bad.value, "status_code", None) == 401
    finally:
        session.close()
        engine.dispose()


# --------------------------------------------------------------------------- readiness / probe

def test_ready_is_503_not_500_when_engine_cannot_be_created(client, monkeypatch):
    """A broken DATABASE_URL must surface as an honest 503 on the readiness endpoint (with a
    server-side traceback), never as an unhandled 500 from a dependency."""
    import app.db.session as db_session

    def _boom():
        raise RuntimeError("simulated NoSuchModuleError: bad dialect")

    # the endpoint imports get_sessionmaker from the module at call time
    monkeypatch.setattr(db_session, "get_sessionmaker", _boom)
    r = client.get("/api/v1/ready")
    assert r.status_code == 503, r.text
    assert r.json()["status"] == "unavailable"
    # with the real sessionmaker the endpoint answers honestly again
    monkeypatch.undo()
    ok = client.get("/api/v1/ready")
    assert ok.status_code == 200 and ok.json()["status"] == "ready"


def test_ready_reports_503_body_when_engine_creation_fails(client, monkeypatch, caplog):
    """Direct 503 contract: patch inside the handler's import path and assert the response."""
    import app.db.session as db_session

    class _Broken:
        def __call__(self):
            raise RuntimeError("engine creation failed (bad DATABASE_URL)")

    monkeypatch.setattr(db_session, "get_sessionmaker", _Broken())
    # The handler does `from app.db.session import get_sessionmaker` at call time, so the
    # patched attribute is what it sees.
    with caplog.at_level(logging.ERROR):
        r = client.get("/api/v1/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable"
    assert "engine creation failed" in caplog.text  # full detail stays server-side
    assert "engine creation failed" not in r.text  # and never leaks to the client


def test_startup_probe_logs_and_survives_unreachable_database(monkeypatch, caplog):
    import app.db.session as db_session

    def _boom():
        raise RuntimeError("cannot reach database")

    monkeypatch.setattr(db_session, "get_sessionmaker", _boom)
    from app.main import _startup_database_probe

    with caplog.at_level(logging.ERROR):
        _startup_database_probe()  # must not raise: the process has to stay up for /ready
    assert "DATABASE PROBE FAILED" in caplog.text
    assert "alembic upgrade head" in caplog.text or "DATABASE_URL" in caplog.text
    assert "cannot reach database" in caplog.text  # traceback preserved server-side


def test_startup_probe_reports_missing_migrations(monkeypatch, caplog, db):
    """A reachable database WITHOUT the alembic bookkeeping must be called out explicitly."""
    db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    db.commit()
    try:
        from app.main import _startup_database_probe

        with caplog.at_level(logging.ERROR):
            _startup_database_probe()
        assert "MIGRATIONS NOT APPLIED" in caplog.text
        assert "alembic upgrade head" in caplog.text
    finally:
        from alembic import command
        from tests.conftest import alembic_cfg

        # The schema is already at head, so only the bookkeeping table is restored —
        # a full `upgrade head` would re-run every migration against existing tables.
        command.stamp(alembic_cfg(), "head")
        db.rollback()


# --------------------------------------------------------------------------- proxy client IPs

def test_client_ip_prefers_last_forwarded_entry():
    from app.core.context import client_ip

    assert client_ip("1.2.3.4, 5.6.7.8", "10.0.0.1") == "5.6.7.8"  # proxy-appended entry wins
    assert client_ip("  spoofed ", "10.0.0.1") == "spoofed"
    assert client_ip(None, "10.0.0.1") == "10.0.0.1"
    assert client_ip("", None) is None
    # untrusted deployments can disable the header entirely
    assert client_ip("1.2.3.4", "10.0.0.1", trust_proxy_headers=False) == "10.0.0.1"


def _fake_request(xff: str | None, peer: str = "proxy.internal"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(
        headers=SimpleNamespace(get=lambda k, _h=headers: _h.get(k)),
        client=SimpleNamespace(host=peer),
    )


def test_rate_limit_buckets_are_per_client_behind_a_proxy(monkeypatch):
    """Behind Render, request.client is the proxy: without XFF handling EVERY user would
    share one 10-requests/minute login bucket."""
    import app.core.rate_limit as rl

    cfg = SimpleNamespace(rate_limit_enabled=True, login_rate_limit_per_minute=2, trust_proxy_headers=True)
    monkeypatch.setattr(rl, "get_settings", lambda: cfg)
    rl.reset_rate_limits()
    dep = rl.rate_limit("login", "login_rate_limit_per_minute")

    dep(_fake_request("203.0.113.10"))
    dep(_fake_request("203.0.113.10"))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        dep(_fake_request("203.0.113.10"))
    assert exc.value.status_code == 429
    # a different end-user is NOT blocked by someone else's bucket
    dep(_fake_request("203.0.113.99"))
    # trust disabled → the proxy peer becomes the shared key again (documented behaviour)
    cfg.trust_proxy_headers = False
    rl.reset_rate_limits()
    dep(_fake_request("203.0.113.10"))
    dep(_fake_request("203.0.113.10"))
    with pytest.raises(HTTPException):
        dep(_fake_request("203.0.113.10"))


# --------------------------------------------------------------------------- seed safety

def test_seed_refuses_to_truncate_production(monkeypatch):
    """python -m scripts.seed would TRUNCATE every table; in production it must refuse."""
    import scripts.seed as seed_mod

    monkeypatch.setattr(seed_mod, "settings", SimpleNamespace(environment="production"))
    called = []
    monkeypatch.setattr(seed_mod, "SessionLocal", lambda: called.append(1) or SimpleNamespace())
    with pytest.raises(SystemExit) as exc:
        seed_mod.main()
    assert exc.value.code == 2
    assert not called, "no database session may be opened before the guard"


def test_seed_runs_outside_production(monkeypatch):
    """Outside production the guard must NOT fire: execution proceeds to session creation."""
    import scripts.seed as seed_mod

    monkeypatch.setattr(seed_mod, "settings", SimpleNamespace(environment="development"))
    monkeypatch.setattr(seed_mod, "os", SimpleNamespace(environ={}, getenv=lambda k, d=None: None))

    def _stop_at_session():
        raise RuntimeError("reached the seeding stage")

    monkeypatch.setattr(seed_mod, "SessionLocal", _stop_at_session)
    with pytest.raises(RuntimeError, match="reached the seeding stage"):
        seed_mod.main()


# --------------------------------------------------------------------------- packaging

def test_requirements_ships_every_runtime_import():
    """`dns` (dnspython) was imported by the investigation tools but missing from
    requirements.txt, so the tools degraded in production while working locally."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    imported: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])

    import sys

    stdlib = set(sys.stdlib_module_names) | {"app", "typing_extensions"}
    requirement_names = set()
    for line in (root.parent / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            requirement_names.add(line.split("==")[0].strip().lower().replace("_", "-"))

    module_to_dist = {"PIL": "pillow", "imagehash": "imagehash", "jwt": "pyjwt",
                      "sqlalchemy": "sqlalchemy", "pydantic_settings": "pydantic-settings",
                      "multipart": "python-multipart", "email_validator": "email-validator",
                      "dns": "dnspython"}
    missing = []
    for mod in sorted(imported):
        if mod in stdlib:
            continue
        dist = module_to_dist.get(mod, mod.lower().replace("_", "-"))
        if dist not in requirement_names:
            missing.append(mod)
    assert not missing, f"runtime imports missing from requirements.txt: {missing}"
