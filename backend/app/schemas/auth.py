from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole
from app.schemas.common import ORM


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    # Optional: an organization ("workspace") name for organization signups. When omitted the
    # account is an individual and receives the standard personal brand scope ("Self").
    organization_name: str | None = Field(None, min_length=2, max_length=200)


class VerifyEmailRequest(BaseModel):
    """Confirm the 6-digit signup OTP. `code` is format-validated (422 on malformed input);
    existence/state is never disclosed by the 400 path (generic error)."""
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    """Uniform for unknown / verified / pending addresses (no enumeration).
    `retry_after_seconds` is a static config value on `accepted` and the remaining
    cooldown on `cooldown`; `dev_otp` only appears outside production with no provider."""

    status: str = "accepted"  # accepted | cooldown
    email_sent: bool = False
    retry_after_seconds: int | None = None
    dev_otp: str | None = None
    dev_only: bool = False


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class OrganizationOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    is_active: bool
    created_at: datetime


class OrgBrief(ORM):
    """Minimal organization summary embedded in user responses."""

    id: uuid.UUID
    name: str


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str | None = Field(None, max_length=2000)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    organization_id: uuid.UUID | None
    organization: OrgBrief | None = None
    preferences: dict | None = None
    created_at: datetime
    last_login_at: datetime | None = None
    email_verified_at: datetime | None = None


class RegisterResponse(BaseModel):
    """Uniform registration result — identical shape whether or not the address already
    had an account (no enumeration). `dev_otp` is only populated outside production when
    no email provider is configured; it is never returned in production. `status` is
    `verification_required` when the message left the process, `delivery_failed` when it
    did not (the UI must not claim an email was sent in that case)."""

    status: str = "verification_required"
    email: str
    verification_required: bool = True
    email_sent: bool = False
    dev_otp: str | None = None
    dev_only: bool = False


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    role: UserRole
    organization_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    role: UserRole | None = None
    is_active: bool | None = None
    organization_id: uuid.UUID | None = None
    clear_organization: bool = False
    password: str | None = Field(None, max_length=256)


class RoleInfo(BaseModel):
    role: UserRole
    permissions: list[str]


# ---- password recovery / self-service profile ----
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    status: str = "sent"
    dev_reset_token: str | None = None
    dev_only: bool = False


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UpdateMeRequest(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    preferences: dict | None = None


class OrganizationDetail(ORM):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    member_count: int = 0
    brand_count: int = 0


class OrganizationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
