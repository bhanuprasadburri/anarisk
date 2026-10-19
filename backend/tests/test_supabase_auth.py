from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import text

from app.core.errors import UnauthorizedError
from app.core import supabase_auth
from app.models import Organization, User
from app.models.enums import UserRole


ISSUER = "https://project-ref.supabase.co/auth/v1"


def _claims(**overrides):
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": "authenticated",
        "exp": now + timedelta(minutes=10),
        "iat": now,
        "sub": str(uuid.uuid4()),
        "email": "user@example.com",
        "role": "authenticated",
        "is_anonymous": False,
    }
    payload.update(overrides)
    return payload


def _settings():
    return SimpleNamespace(
        supabase_url="https://project-ref.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        supabase_jwt_audience="authenticated",
        supabase_auth_enabled=True,
    )


def test_verifies_asymmetric_supabase_jwt_claims(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    token = jwt.encode(_claims(), private_key, algorithm="ES256", headers={"kid": "test-key"})

    class Client:
        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(algorithm_name="ES256", key=public_key)

    monkeypatch.setattr(supabase_auth, "get_settings", _settings)
    monkeypatch.setattr(supabase_auth, "_jwks_client", lambda _url: Client())
    payload = supabase_auth.verify_access_token(token)
    assert payload["role"] == "authenticated"
    assert payload["aud"] == "authenticated"


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "anon"},
        {"role": "service_role"},
        {"is_anonymous": True},
        {"email": ""},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
def test_rejects_invalid_asymmetric_claims(monkeypatch, changes):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    token = jwt.encode(_claims(**changes), private_key, algorithm="ES256", headers={"kid": "test-key"})

    class Client:
        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(algorithm_name="ES256", key=public_key)

    monkeypatch.setattr(supabase_auth, "get_settings", _settings)
    monkeypatch.setattr(supabase_auth, "_jwks_client", lambda _url: Client())
    with pytest.raises(UnauthorizedError):
        supabase_auth.verify_access_token(token)


def test_hs256_uses_supabase_auth_user_endpoint(monkeypatch):
    payload = _claims()
    token = jwt.encode(payload, "shared-test-key", algorithm="HS256")
    calls = []

    class Response:
        status_code = 200

    def fake_get(url, *, headers, timeout):
        calls.append((url, headers, timeout))
        return Response()

    monkeypatch.setattr(supabase_auth, "get_settings", _settings)
    monkeypatch.setattr(supabase_auth.httpx, "get", fake_get)
    assert supabase_auth.verify_access_token(token)["sub"] == payload["sub"]
    assert calls[0][0] == "https://project-ref.supabase.co/auth/v1/user"
    assert calls[0][1]["apikey"] == "sb_publishable_test"


def test_admin_invite_uses_server_secret_and_password_setup_redirect(monkeypatch):
    created_id = uuid.uuid4()
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": str(created_id)}

    def fake_post(url, *, params, headers, json, timeout):
        calls.append((url, params, headers, json, timeout))
        return Response()

    monkeypatch.setattr(supabase_auth, "get_settings", lambda: SimpleNamespace(
        supabase_url="https://project-ref.supabase.co",
        supabase_secret_key="sb_secret_test_only",
        frontend_url="https://anarisk1-pkvr.vercel.app",
    ))
    monkeypatch.setattr(supabase_auth.httpx, "post", fake_post)
    assert supabase_auth.invite_user("new@example.com", "New User") == created_id
    assert calls[0][0] == "https://project-ref.supabase.co/auth/v1/invite"
    assert calls[0][1]["redirect_to"].endswith("/reset-password")
    assert calls[0][2]["apikey"] == "sb_secret_test_only"
    assert "Authorization" not in calls[0][2]
    assert calls[0][3] == {"email": "new@example.com", "data": {"full_name": "New User"}}


def test_existing_profile_link_keeps_server_role(db, monkeypatch):
    user = User(
        email="user@example.com",
        full_name="Existing User",
        hashed_password="not-used-in-this-test",
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    from app.api.deps import _supabase_user

    # Link by verified email on first sign-in, preserving the existing admin assignment.
    subject = uuid.uuid4()
    monkeypatch.setattr("app.api.deps.get_confirmed_user", lambda _token: {
        "id": str(subject), "email": user.email,
        "email_confirmed_at": "2026-01-01T00:00:00Z", "user_metadata": {},
    })
    resolved = _supabase_user("verified-token", {"sub": str(subject), "email": user.email}, db)
    assert resolved.id == user.id
    assert resolved.supabase_user_id == subject
    assert resolved.role == UserRole.ADMIN


def test_new_profile_ignores_untrusted_role_metadata(db, monkeypatch):
    subject = uuid.uuid4()
    monkeypatch.setattr("app.api.deps.get_confirmed_user", lambda _token: {
        "id": str(subject),
        "email": "new-user@example.com",
        "email_confirmed_at": "2026-01-01T00:00:00Z",
        "user_metadata": {
            "full_name": "New User",
            "organization_name": "New Workspace",
            "role": "administrator",
            "organization_id": str(uuid.uuid4()),
        },
    })

    from app.api.deps import _supabase_user

    user = _supabase_user("verified-token", {"sub": str(subject), "email": "new-user@example.com"}, db)
    assert user.role == UserRole.BRAND_OWNER
    assert user.supabase_user_id == subject
    assert user.organization.name == "New Workspace"
    assert db.query(Organization).filter(Organization.id == user.organization_id).count() == 1


def test_application_tables_have_rls_enabled(db):
    migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261019_0011_supabase_data_api_rls.py"
    spec = spec_from_file_location("supabase_rls_migration", migration_path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    rows = db.execute(text(
        "SELECT relname FROM pg_class "
        "WHERE relnamespace = 'public'::regnamespace AND relrowsecurity"
    )).scalars().all()
    assert set(migration._TABLES).issubset(set(rows))
