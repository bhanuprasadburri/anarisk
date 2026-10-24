"""Isolated test harness.

* Uses TEST_DATABASE_URL (default: .../nimbus_test) and REFUSES to run unless the database name ends with '_test'.
* Schema is created with the real Alembic migrations (so migrations are exercised on every run).
* Every test starts from empty tables; uploads go to a temp directory.
"""
import os
import tempfile
import uuid
from datetime import UTC, datetime

from sqlalchemy.engine import make_url

_TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://nimbus:nimbus_dev_pw@localhost:5432/nimbus_test")
if not make_url(_TEST_URL).database.endswith("_test"):
    raise RuntimeError("Refusing to run tests: database name must end with '_test'")

from app.db.url import normalize_database_url  # noqa: E402  (no settings read at import time)

_TEST_URL = normalize_database_url(_TEST_URL)  # provider-style URLs (postgres:// …) work too
_UPLOADS = tempfile.mkdtemp(prefix="nn_test_uploads_")
os.environ.update({
    "ENVIRONMENT": "test", "DATABASE_URL": _TEST_URL, "SECRET_KEY": "test-secret-key-test-secret-key-0123456789", "UPLOAD_DIR": _UPLOADS,
    "RATE_LIMIT_ENABLED": "false", "BCRYPT_ROUNDS": "4", "ALLOW_PUBLIC_REGISTRATION": "true", "URL_FETCH_ENABLED": "false", "DEBUG": "false",
    # Hermetic: never read the developer's .env email settings; individual tests opt in to "memory".
    "EMAIL_PROVIDER": "none",
    # Hermetic: a developer .env may set SUPABASE_URL, which flips supabase_auth_enabled and
    # would redirect every login test to the Supabase flow (HTTP 410). The default test auth
    # path is AnaRisk's own login; tests exercising Supabase override settings directly.
    "SUPABASE_URL": "",
})

import io  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Organization, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services.users import reset_resend_cooldowns  # noqa: E402

PASSWORD = "Test-Passw0rd!"


from functools import lru_cache


@lru_cache
def _db_is_available() -> bool:
    try:
        eng = create_engine(_TEST_URL, connect_args={"connect_timeout": 1})
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


def alembic_cfg() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _TEST_URL)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    if not _db_is_available():
        yield
        return
    eng = create_engine(_TEST_URL)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    eng.dispose()
    command.upgrade(alembic_cfg(), "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    reset_rate_limits()
    reset_resend_cooldowns()
    if not _db_is_available():
        yield
        return
    eng = create_engine(_TEST_URL)
    tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    eng.dispose()
    yield


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db():
    if not _db_is_available():
        pytest.skip("Test database not reachable")
    from app.db.session import get_sessionmaker

    s: Session = get_sessionmaker()()
    yield s
    s.close()


@pytest.fixture
def client():
    if not _db_is_available():
        pytest.skip("Test database not reachable")
    with TestClient(app) as c:
        yield c


class Factory:
    def __init__(self, db: Session, client: TestClient):
        self.db, self.client = db, client

    def org(self, name="Org A") -> Organization:
        o = Organization(name=name, slug=name.lower().replace(" ", "-") + "-" + uuid.uuid4().hex[:6])
        self.db.add(o)
        self.db.commit()
        return o

    def user(self, role: UserRole, org: Organization | None = None, email: str | None = None, active: bool = True) -> User:
        # Factory users stand in for admin/seed-created accounts: created already verified,
        # exactly like real accounts outside the public-OTP signup flow.
        u = User(email=email or f"{role.value}-{uuid.uuid4().hex[:8]}@test.example", full_name=f"{role.value} user", role=role,
                 organization_id=org.id if org else None, hashed_password=hash_password(PASSWORD), is_active=active,
                 email_verified_at=datetime.now(UTC))
        self.db.add(u)
        self.db.commit()
        return u

    def headers(self, user: User) -> dict:
        r = self.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def brand(self, h, org: Organization, name="AcmeBank", refs=True) -> dict:
        r = self.client.post("/api/v1/brands", json={"organization_id": str(org.id), "name": name}, headers=h)
        assert r.status_code == 201, r.text
        b = r.json()
        if refs:
            for kind, value, platform in [("name", name, None), ("domain", "acmebank.example", None), ("handle", "acmebank", "x"),
                                          ("app_package", "com.acmebank.mobile", None), ("publisher", "AcmeBank Ltd", None),
                                          ("bio", "AcmeBank - secure everyday banking for everyone. Customer care is available 24/7 through the official app.", None)]:
                rr = self.client.post(f"/api/v1/brands/{b['id']}/references", json={"kind": kind, "value": value, "platform": platform}, headers=h)
                assert rr.status_code == 201, rr.text
        return b

    def entity(self, h, brand_id: str, etype: str, analyze=False, **kw) -> dict:
        body = {"brand_id": brand_id, "entity_type": etype, "analyze": analyze, **kw}
        r = self.client.post("/api/v1/entities", json=body, headers=h)
        assert r.status_code == 201, r.text
        return r.json()["entity"]

    def profile(self, h, brand_id, handle="acmebank_support", platform="x", **attrs) -> dict:
        return self.entity(h, brand_id, "social_profile", platform=platform, attributes={"handle": handle, **attrs})

    def website(self, h, brand_id, url="https://acmebank-login.xyz/verify", **attrs) -> dict:
        return self.entity(h, brand_id, "website", attributes={"url": url, **attrs})


@pytest.fixture
def f(db, client) -> Factory:
    return Factory(db, client)


@pytest.fixture
def world(f):
    """org A (admin, investigator, brand owner, partner) + org B outsider, one brand in org A."""
    a, b = f.org("Org A"), f.org("Org B")
    admin, inv = f.user(UserRole.ADMIN), f.user(UserRole.INVESTIGATOR, a)
    owner, partner = f.user(UserRole.BRAND_OWNER, a), f.user(UserRole.PARTNER, a)
    outsider = f.user(UserRole.INVESTIGATOR, b)
    outsider_owner = f.user(UserRole.BRAND_OWNER, b)
    h = {n: f.headers(u) for n, u in dict(admin=admin, inv=inv, owner=owner, partner=partner, outsider=outsider, outsider_owner=outsider_owner).items()}
    brand = f.brand(h["owner"], a)
    class W: pass
    w = W()
    w.org_a, w.org_b, w.users, w.h, w.brand = a, b, dict(admin=admin, inv=inv, owner=owner, partner=partner, outsider=outsider, outsider_owner=outsider_owner), h, brand
    return w


def png_bytes(variant="official", size=256) -> bytes:
    """Deterministic synthetic logos: 'official' vs near-copy vs unrelated."""
    im = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(im)
    if variant in ("official", "copy"):
        d.ellipse((30, 30, 226, 226), fill=(10, 40, 120) if variant == "official" else (20, 50, 130))
        d.polygon([(80, 190), (128, 60), (176, 190), (150, 190), (128, 120), (106, 190)], fill="white")
        d.rectangle((100, 150, 156, 164), fill="white")
        if variant == "copy":
            d.rectangle((0, 0, 255, 6), fill=(20, 50, 130))
    else:
        for i in range(0, size, 32):
            d.rectangle((i, 0, i + 15, size - 1), fill=(200, 30, 30))
        d.ellipse((90, 90, 170, 170), fill="black")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()
