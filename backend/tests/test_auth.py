from datetime import timedelta

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.enums import UserRole
from tests.conftest import PASSWORD


def test_register_creates_orgless_brand_owner_and_hides_hash(client, db):
    r = client.post("/api/v1/auth/register", json={"email": "New@Test.Example", "full_name": "New User", "password": PASSWORD})
    assert r.status_code == 201
    body = r.json()
    # uniform verification response: email echoed, nothing sensitive, no role/org disclosure
    assert body["email"] == "new@test.example" and body["verification_required"] is True
    assert "hashed_password" not in body and "password" not in body and "id" not in body
    from app.models import User
    u = db.query(User).one()
    assert u.role.value == "brand_owner" and u.organization_id is None  # forced server-side
    assert u.email_verified_at is None  # not activated until the OTP is confirmed
    assert u.hashed_password != PASSWORD and u.hashed_password.startswith("$2")


def test_register_cannot_choose_role_or_org(client, db):
    r = client.post("/api/v1/auth/register", json={"email": "x@test.example", "full_name": "X", "password": PASSWORD, "role": "administrator"})
    assert r.status_code == 201 and "role" not in r.json()  # the response never reflects caller-chosen roles
    from app.models import User
    u = db.query(User).one()
    assert u.role.value == "brand_owner" and u.organization_id is None


def test_register_weak_password_and_duplicate(client, db):
    assert client.post("/api/v1/auth/register", json={"email": "a@test.example", "full_name": "A", "password": "short1"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "a@test.example", "full_name": "A", "password": "onlyletterslong"}).status_code == 422
    r1 = client.post("/api/v1/auth/register", json={"email": "a@test.example", "full_name": "A", "password": PASSWORD})
    assert r1.status_code == 201
    # duplicate registration: uniform 201 (no email_taken disclosure) and still one account
    r2 = client.post("/api/v1/auth/register", json={"email": "A@test.example", "full_name": "A", "password": PASSWORD})
    assert r2.status_code == 201
    assert set(r2.json().keys()) == set(r1.json().keys())
    from app.models import User
    assert db.query(User).count() == 1


def test_registration_can_be_disabled(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "allow_public_registration", False)
    r = client.post("/api/v1/auth/register", json={"email": "a@test.example", "full_name": "A", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_disabled"


def test_login_success_and_me(client, f):
    u = f.user(UserRole.INVESTIGATOR, f.org())
    r = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer" and r.json()["expires_in"] > 0
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == u.email and "hashed_password" not in me.json()


def test_oauth2_form_token_endpoint(client, f):
    u = f.user(UserRole.INVESTIGATOR, f.org())
    r = client.post("/api/v1/auth/token", data={"username": u.email, "password": PASSWORD})
    assert r.status_code == 200 and "access_token" in r.json()


def test_login_failures_are_indistinguishable(client, f):
    u = f.user(UserRole.INVESTIGATOR, f.org())
    inactive = f.user(UserRole.INVESTIGATOR, f.org("B"), active=False)
    wrong = client.post("/api/v1/auth/login", json={"email": u.email, "password": "Wrong-Passw0rd!"})
    missing = client.post("/api/v1/auth/login", json={"email": "ghost@test.example", "password": PASSWORD})
    disabled = client.post("/api/v1/auth/login", json={"email": inactive.email, "password": PASSWORD})
    for r in (wrong, missing, disabled):
        assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid email or password"
        assert r.headers["www-authenticate"] == "Bearer"
    assert wrong.json() == missing.json() == disabled.json()


def test_missing_invalid_and_expired_tokens(client, f):
    u = f.user(UserRole.INVESTIGATOR, f.org())
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    expired, _ = create_access_token(u.id, expires_minutes=-5)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


def test_token_signed_with_other_key_or_alg_none_rejected(client, f):
    import jwt
    u = f.user(UserRole.INVESTIGATOR, f.org())
    forged = jwt.encode({"sub": str(u.id), "exp": 9999999999, "iat": 1, "typ": "access"}, "another-secret-another-secret-123456", algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_tok = jwt.encode({"sub": str(u.id), "exp": 9999999999, "iat": 1, "typ": "access"}, None, algorithm="none")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {none_tok}"}).status_code == 401


def test_deactivated_user_token_stops_working_immediately(client, f, db):
    u = f.user(UserRole.INVESTIGATOR, f.org())
    h = f.headers(u)
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    u.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_password_hashing_roundtrip_and_long_passwords():
    long_pw = "A1" + "x" * 200
    h = hash_password(long_pw)
    assert verify_password(long_pw, h) and not verify_password(long_pw[:-1] + "y", h)  # not truncated at 72 bytes


def test_login_rate_limit(client, f, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 3)
    codes = [client.post("/api/v1/auth/login", json={"email": "x@test.example", "password": "bad"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    r = client.post("/api/v1/auth/login", json={"email": "x@test.example", "password": "bad"})
    assert "retry-after" in r.headers and r.json()["error"]["code"] == "rate_limited"


def test_admin_user_management_and_guards(client, f):
    org = f.org()
    admin = f.user(UserRole.ADMIN)
    h = f.headers(admin)
    r = client.post("/api/v1/users", json={"email": "inv@test.example", "full_name": "Inv", "password": PASSWORD, "role": "investigator", "organization_id": str(org.id)}, headers=h)
    assert r.status_code == 201 and r.json()["role"] == "investigator"
    uid = r.json()["id"]
    assert client.patch(f"/api/v1/users/{uid}", json={"is_active": False}, headers=h).json()["is_active"] is False
    assert client.patch(f"/api/v1/users/{admin.id}", json={"role": "partner"}, headers=h).status_code == 403
    assert client.patch(f"/api/v1/users/{admin.id}", json={"is_active": False}, headers=h).status_code == 403
    assert client.get("/api/v1/users", headers=h).json()["total"] == 2
    roles = client.get("/api/v1/users/roles", headers=h).json()
    assert {r["role"] for r in roles} == {"administrator", "investigator", "brand_owner", "partner"}


def test_decode_rejects_wrong_type(f):
    import jwt
    from app.core.errors import UnauthorizedError
    import pytest
    tok = jwt.encode({"sub": "x", "exp": 9999999999, "iat": 1, "typ": "refresh"}, "test-secret-key-test-secret-key-0123456789", algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        decode_access_token(tok)


def test_login_db_failure_returns_generic_500_and_logs_traceback(client, f, monkeypatch, caplog):
    """A database outage during login must surface as the uniform generic internal_error to the
    client while the FULL traceback is preserved server-side — and never the password."""
    import logging

    import app.services.users as users_svc

    u = f.user(UserRole.INVESTIGATOR, f.org())

    def _outage(db, email, password):
        raise RuntimeError("simulated database outage")

    monkeypatch.setattr(users_svc, "authenticate", _outage)
    with caplog.at_level(logging.ERROR):
        r = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal_error" and body["error"]["message"] == "Internal server error"
    # generic to the client, full detail in the server log
    assert "simulated database outage" not in r.text
    assert "simulated database outage" in caplog.text and "RuntimeError" in caplog.text
    assert PASSWORD not in caplog.text


def test_login_token_creation_failure_is_generic_500(client, f, monkeypatch, caplog):
    """If JWT signing fails AFTER the password checked out, the client still gets the anonymous
    500; the traceback lands in the server log with no credential material in either."""
    import logging

    import app.services.users as users_svc

    u = f.user(UserRole.INVESTIGATOR, f.org())

    def _signer_down(user_id, **kwargs):
        raise RuntimeError("jwt signer unavailable")

    monkeypatch.setattr(users_svc, "create_access_token", _signer_down)
    with caplog.at_level(logging.ERROR):
        r = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "jwt signer unavailable" not in r.text
    assert "jwt signer unavailable" in caplog.text and "RuntimeError" in caplog.text
    assert PASSWORD not in caplog.text


def test_login_domain_errors_pass_through_unaffected(client, f, db):
    """The safety net must not swallow domain outcomes: login failures stay a uniform
    401 invalid_credentials — an unverified account is byte-identical to an unknown email."""
    u = f.user(UserRole.INVESTIGATOR, f.org())
    u.email_verified_at = None
    db.commit()
    r = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    unknown = client.post("/api/v1/auth/login", json={"email": "no-such-user@example.com", "password": PASSWORD})
    assert r.status_code == unknown.status_code == 401
    assert r.json() == unknown.json(), "unverified accounts must be indistinguishable from unknown ones"
    bad = client.post("/api/v1/auth/login", json={"email": u.email, "password": "Wrong-Passw0rd!"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
