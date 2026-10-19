import logging

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import DomainError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest, ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, RegisterRequest, RegisterResponse,
    ResendVerificationRequest, ResendVerificationResponse, ResetPasswordRequest, TokenResponse, UpdateMeRequest, UserOut,
    VerifyEmailRequest,
)
from app.services import users as users_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _authenticate_safely(db: Session, email: str, password: str) -> tuple[str, int]:
    """Run the login check, converting unexpected failures into the uniform generic 500.

    DomainError subclasses (401 invalid credentials — uniform for unknown email, wrong password,
    inactive and unverified accounts — …) pass through untouched. Anything else — a database
    outage, a broken JWT signer — is logged HERE with the full server-side traceback (never the
    password) and returned to the client as the same anonymous ``internal_error`` body the global
    handler produces.
    """
    try:
        return users_svc.authenticate(db, email, password)
    except DomainError:
        raise
    except Exception:
        log.exception("Unexpected error during login (email=%s)", email)
        raise DomainError("Internal server error", code="internal_error", status_code=500) from None


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit("register", "register_rate_limit_per_minute"))],
             summary="Self-register (brand_owner role, no organization until an administrator assigns one). "
                     "Creates the account UNVERIFIED and emails a 6-digit OTP (uniform response whether or not "
                     "the address already exists — no account enumeration). dev_otp only outside production "
                     "with no email provider configured.")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    return RegisterResponse.model_validate(users_svc.register_public(db, body.email, body.full_name, body.password))


@router.post("/verify-email", response_model=UserOut,
             dependencies=[Depends(rate_limit("verify_email", "login_rate_limit_per_minute"))],
             summary="Confirm the 6-digit OTP from the verification email (single-use, attempt-limited, "
                     "TTL-bound). Generic 400 on any failure — never reveals whether the address exists.")
def verify_email(body: VerifyEmailRequest, db: Session = Depends(get_db)):
    return users_svc.verify_email(db, body.email, body.code)


@router.post("/resend-verification", response_model=ResendVerificationResponse,
             dependencies=[Depends(rate_limit("resend_verification", "register_rate_limit_per_minute"))],
             summary="Resend the signup OTP (or a generic notice). Uniform for unknown/verified/pending "
                     "addresses (no enumeration); per-email cooldown; email_sent reports honest delivery.")
def resend_verification(body: ResendVerificationRequest, db: Session = Depends(get_db)):
    result = users_svc.resend_verification(db, body.email)
    return ResendVerificationResponse(**result)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", "login_rate_limit_per_minute"))], summary="Login with JSON credentials")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    token, expires = _authenticate_safely(db, body.email, body.password)
    return TokenResponse(access_token=token, expires_in=expires)


@router.post("/token", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", "login_rate_limit_per_minute"))], summary="OAuth2 password form (used by Swagger 'Authorize')")
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    token, expires = _authenticate_safely(db, form.username, form.password)
    return TokenResponse(access_token=token, expires_in=expires)


@router.get("/me", response_model=UserOut, summary="Current user (incl. preferences and organization summary)")
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut, summary="Update your own profile (full name, email, preferences)")
def update_me(body: UpdateMeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return users_svc.update_own_profile(db, user, body)


@router.post("/forgot-password", response_model=ForgotPasswordResponse,
             dependencies=[Depends(rate_limit("forgot_password", "login_rate_limit_per_minute"))],
             summary="Request a password-reset link. Always 200 - unknown emails behave like known ones (no user enumeration).")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    return users_svc.forgot_password(db, body.email)


@router.post("/reset-password", response_model=UserOut,
             dependencies=[Depends(rate_limit("reset_password", "login_rate_limit_per_minute"))],
             summary="Set a new password with a valid reset token (400 invalid_or_expired_token otherwise)")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    return users_svc.reset_password(db, body.token, body.new_password)


@router.post("/change-password", response_model=UserOut, summary="Change your password (authenticated; current password required)")
def change_password(body: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return users_svc.change_password(db, user, body.current_password, body.new_password)
