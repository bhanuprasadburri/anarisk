"""Application settings, loaded from environment variables / .env.

All scoring weights, thresholds and workflow rules that the project documentation calls
"configurable" live here. The numbers are ILLUSTRATIVE HEURISTICS and require validation against
labelled data before being relied on operationally.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger(__name__)

PLACEHOLDER_SECRET = "change-me-in-production-this-is-only-a-development-placeholder"

# Case workflow. Keys/values are CaseStatus values (see models/enums.py).
DEFAULT_CASE_TRANSITIONS: dict[str, list[str]] = {
    "detected": ["triaged"],
    "triaged": ["under_review", "resolved"],  # resolved = documented shortcut (dismiss false positive)
    "under_review": ["assigned", "triaged", "resolved"],  # resolved = documented shortcut
    "assigned": ["escalated", "under_review", "resolved"],
    "escalated": ["resolved", "assigned"],  # assigned = de-escalation / take back
    "resolved": ["under_review"],  # reopen (needs case:reopen permission)
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AnaRisk - Digital Risk Protection API"
    app_version: str = "1.0.0"
    environment: str = "development"  # development | test | production
    debug: bool = False

    database_url: str = "postgresql+psycopg://nimbus:nimbus_dev_pw@localhost:5432/nimbus"
    test_database_url: str = "postgresql+psycopg://nimbus:nimbus_dev_pw@localhost:5432/nimbus_test"

    secret_key: str = PLACEHOLDER_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bcrypt_rounds: int = 12  # keep >= 12 outside of tests

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    allow_public_registration: bool = True
    bootstrap_admin_email: str = "admin@nimbus.example"
    bootstrap_admin_password: str = "ChangeMe-Admin-123"

    # ---- email delivery (real transactional email) ----
    # provider: none (dev fallback only) | smtp | resend
    email_provider: str = "none"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_use_ssl: bool = False
    resend_api_key: str = ""
    resend_api_base_url: str = "https://api.resend.com"
    email_from_address: str = "bhanuburri28@gmail.com"
    email_from_name: str = "AnaRisk"
    frontend_url: str = "http://localhost:3000"
    email_max_retries: int = 1
    email_timeout_seconds: float = 10.0
    # ---- email OTP verification (signup / profile email change) ----
    # The 6-digit code is stored only as an HMAC-SHA256 hash keyed by SECRET_KEY.
    otp_ttl_minutes: int = 10          # short-lived by design; a new code can be requested after this
    otp_max_attempts: int = 5          # wrong attempts per code before that code is locked out
    resend_verification_cooldown_seconds: int = 60  # per-email throttle on resend (uniform: known or unknown addresses)

    # ---- AI analysis provider (optional; deterministic fallback when absent) ----
    # provider: none | openai-compatible (works with OpenAI, Azure OpenAI-compatible gateways, Ollama, etc.)
    ai_provider: str = "none"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = ""
    ai_timeout_seconds: float = 30.0
    ai_max_tokens: int = 1500

    # ---- background monitoring worker (DB-scheduled; safe across multiple processes) ----
    monitoring_worker_enabled: bool = True
    monitoring_interval_seconds: int = 300
    monitoring_retry_max: int = 3
    monitoring_backoff_seconds: int = 120

    # ---- rate limiting (in-memory, per process; use a shared store behind multiple workers) ----
    rate_limit_enabled: bool = True
    login_rate_limit_per_minute: int = 10
    register_rate_limit_per_minute: int = 5
    analyze_rate_limit_per_minute: int = 60
    # Honour X-Forwarded-For when deriving the client IP (rate limiting + audit rows).
    # Required behind a reverse proxy (Render) where request.client is the proxy; set false
    # only when the service is directly exposed and clients could spoof the header.
    trust_proxy_headers: bool = True

    # ---- uploads ----
    upload_dir: str = "./uploads"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_image_pixels: int = 25_000_000
    allowed_image_formats: list[str] = ["PNG", "JPEG", "WEBP", "GIF"]

    # ---- scoring: R = w1*s1 + w2*s2 + w3*s3 + w4*s4 (normalised to sum 1) ----
    scoring_model_version: str = "heuristic-v1"
    weight_brand_logo: float = 0.30
    weight_impersonation: float = 0.30
    weight_url_risk: float = 0.25
    weight_behavior: float = 0.15

    # severity thresholds on the overall risk score (below `medium` => low)
    severity_medium: float = 0.40
    severity_high: float = 0.60
    severity_critical: float = 0.80

    # confidence = 0.4*evidence_quality + 0.3*availability + 0.3*corroboration
    confidence_w_evidence: float = 0.4
    confidence_w_availability: float = 0.3
    confidence_w_corroboration: float = 0.3
    confidence_medium: float = 0.40
    confidence_high: float = 0.70
    provenance_factor_collected: float = 1.0
    provenance_factor_manual: float = 0.6
    provenance_factor_synthetic: float = 0.3
    synthetic_confidence_cap: float = 0.40

    # ---- detection tuning ----
    image_hash_max_distance: int = 14  # Hamming distance (of 64 bits) at/over which similarity score is 0
    image_hash_near_duplicate: int = 6
    impersonation_min_similarity: float = 0.55
    suspicious_tlds: list[str] = [
        "zip", "mov", "top", "xyz", "click", "link", "work", "support", "country", "gq", "tk", "ml", "cf", "ga",
    ]
    url_shorteners: list[str] = ["bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rb.gy"]
    suspicious_keywords: list[str] = [
        "login", "signin", "verify", "secure", "update", "account", "wallet", "giveaway", "claim", "bonus",
        "password", "support", "refund", "recover", "airdrop", "kyc",
    ]
    account_age_days_thresholds: list[int] = [7, 30, 90, 365]  # score 1.0/0.7/0.4/0.15 then 0
    velocity_posts_per_day_saturation: float = 20.0
    follower_growth_per_day_saturation: float = 500.0
    min_posts_for_velocity: int = 5
    sync_window_seconds: int = 60

    # ---- graph / clustering ----
    graph_min_edge_confidence: float = 0.30
    cluster_min_size: int = 2
    cluster_min_mean_edge_confidence: float = 0.60
    cluster_min_max_risk: float = 0.60
    discovery_image_distance: int = 4

    # ---- case workflow ----
    case_transitions: dict[str, list[str]] = Field(default_factory=lambda: dict(DEFAULT_CASE_TRANSITIONS))

    # ---- outbound URL inspection (SSRF-guarded; OFF by default) ----
    url_fetch_enabled: bool = False
    url_fetch_timeout_seconds: float = 5.0
    url_fetch_max_bytes: int = 512 * 1024
    url_fetch_max_redirects: int = 3
    url_fetch_allowed_ports: list[int] = [80, 443]
    url_fetch_domain_allowlist: list[str] = []  # if non-empty, only these registrable domains may be fetched

    @field_validator("database_url", "test_database_url", mode="before")
    @classmethod
    def _normalize_database_urls(cls, v):
        """Accept the URLs providers actually hand out (postgres://, postgresql:// without a
        driver, psycopg2 URLs) by coercing them to the psycopg 3 driver this build ships.
        Without this, engine creation/connect explodes on the first DB-backed request while
        the DB-less /health check keeps passing (\"deploy OK, login 500\")."""
        from app.db.url import normalize_database_url

        return normalize_database_url(v) if isinstance(v, str) else v

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on", "debug", "dev")
        return bool(v)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [o.strip() for o in s.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _validate(self):
        total = self.weight_brand_logo + self.weight_impersonation + self.weight_url_risk + self.weight_behavior
        if total <= 0 or min(
            self.weight_brand_logo, self.weight_impersonation, self.weight_url_risk, self.weight_behavior
        ) < 0:
            raise ValueError("scoring weights must be non-negative with a positive sum")
        if abs(total - 1.0) > 1e-9:
            log.warning("Scoring weights sum to %.4f; normalising to 1.0", total)
            self.weight_brand_logo /= total
            self.weight_impersonation /= total
            self.weight_url_risk /= total
            self.weight_behavior /= total
        if not (0 < self.severity_medium < self.severity_high < self.severity_critical <= 1):
            raise ValueError("severity thresholds must satisfy 0 < medium < high < critical <= 1")
        c = self.confidence_w_evidence + self.confidence_w_availability + self.confidence_w_corroboration
        if abs(c - 1.0) > 1e-9:
            raise ValueError("confidence component weights must sum to 1")
        if self.email_provider not in ("none", "smtp", "resend", "memory"):
            raise ValueError("EMAIL_PROVIDER must be one of: none, smtp, resend, memory")
        if self.ai_provider not in ("none", "openai-compatible", "memory"):
            raise ValueError("AI_PROVIDER must be one of: none, openai-compatible, memory")
        if self.environment == "production":
            if self.email_provider == "none":
                log.warning("EMAIL_PROVIDER is 'none' in production: password-reset and verification emails will NOT be delivered")
            if self.secret_key == PLACEHOLDER_SECRET or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of >= 32 chars in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must not contain '*' in production")
            if self.debug:
                raise ValueError("DEBUG must be false in production")
        return self

    @property
    def weights(self) -> dict[str, float]:
        return {
            "brand_logo": self.weight_brand_logo,
            "impersonation": self.weight_impersonation,
            "url_risk": self.weight_url_risk,
            "behavior": self.weight_behavior,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
