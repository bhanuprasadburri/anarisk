"""Integration catalog + stored configuration.

Honesty rules enforced here:
  * Secret values are encrypted at rest (Fernet, key derived from SECRET_KEY) and are NEVER returned -
    `config_keys` only echoes "which non-secret fields were set" plus a `••••` marker for secrets.
  * `test` never fakes success: credential-based providers report `ok=false` unless a real, side-effect-free
    verification was possible; dns_whois/web_scraping perform real network checks and report the outcome.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError, NotFoundError, ValidationFailure
from app.models import Brand, IntegrationConfig, User
from app.repositories.access import brand_scope, get_brand_for_user
from app.services import audit, notifications as notify_svc

log = logging.getLogger(__name__)

MASK = "••••"

# ---- provider catalog (module constant) ----
CATALOG: list[dict[str, Any]] = [
    {
        "key": "x_twitter", "name": "X (Twitter)", "category": "social",
        "description": "Search and monitor public X posts/profiles for impersonation of your brand. Requires API credentials with an approved tier.",
        "requires_credentials": True,
        "config_fields": [
            {"key": "bearer_token", "label": "Bearer token", "type": "secret", "required": True, "placeholder": "AAAA..."},
            {"key": "api_key", "label": "API key", "type": "secret", "required": True, "placeholder": "x2n4..."},
            {"key": "api_secret", "label": "API secret", "type": "secret", "required": True, "placeholder": "AbCd..."},
        ],
        "docs_url": "https://developer.x.com/en/docs/twitter-api",
    },
    {
        "key": "instagram", "name": "Instagram", "category": "social",
        "description": "The Graph API can inspect eligible public professional accounts through Business Discovery; it does not provide unrestricted search across personal profiles or hashtags.",
        "requires_credentials": True,
        "config_fields": [
            {"key": "access_token", "label": "Graph API access token", "type": "secret", "required": True, "placeholder": "IGQVJ..."},
            {"key": "business_account_id", "label": "Business account id", "type": "text", "required": True, "placeholder": "17841400..."},
        ],
        "docs_url": "https://developers.facebook.com/docs/instagram-api",
    },
    {
        "key": "google_play", "name": "Google Play", "category": "app_store",
        "description": "The Android Publisher API is for apps in the authorized developer account; it is not a public catalog search API. This project has no live Google Play catalog connector.",
        "requires_credentials": True,
        "config_fields": [
            {"key": "service_account_email", "label": "Google Cloud service-account email", "type": "text", "required": True, "placeholder": "anarisk-monitor@project.iam.gserviceaccount.com"},
            {"key": "private_key", "label": "Service-account private key", "type": "secret", "required": True, "placeholder": "-----BEGIN PRIVATE KEY-----"},
        ],
        "docs_url": "https://developers.google.com/android-publisher",
    },
    {
        "key": "app_store", "name": "Apple App Store", "category": "app_store",
        "description": "App Store Connect API credentials manage resources in the developer's own account; they do not search the public App Store catalog. No live public-catalog connector is implemented.",
        "requires_credentials": True,
        "config_fields": [
            {"key": "issuer_id", "label": "Issuer ID", "type": "text", "required": True, "placeholder": "xxxxxxxx-xxxx-..."},
            {"key": "key_id", "label": "Key ID", "type": "text", "required": True, "placeholder": "XXXXXXXXXX"},
            {"key": "private_key", "label": "Private key (.p8)", "type": "secret", "required": True, "placeholder": "-----BEGIN PRIVATE KEY-----"},
        ],
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi",
    },
    {
        "key": "web_scraping", "name": "Web scraping target", "category": "web",
        "description": "Fetch a specific public URL (SSRF-guarded, timeout-bounded) to verify a suspect page is reachable.",
        "requires_credentials": False,
        "config_fields": [
            {"key": "target_url", "label": "Target URL", "type": "url", "required": True, "placeholder": "https://suspect-example.com/page"},
            {"key": "user_agent", "label": "User agent", "type": "text", "required": False, "placeholder": "AnaRisk-Checker/1.0"},
            {"key": "method", "label": "Request method", "type": "select", "required": False, "options": ["GET", "HEAD"], "placeholder": "GET"},
        ],
    },
    {
        "key": "dns_whois", "name": "DNS / WHOIS lookup", "category": "infrastructure",
        "description": "Resolve a domain with a real DNS lookup (no credentials). WHOIS details still require a WHOIS data source.",
        "requires_credentials": False,
        "config_fields": [
            {"key": "check_domain", "label": "Domain to check", "type": "text", "required": False, "placeholder": "example.com"},
        ],
    },
    {
        "key": "url_scan", "name": "URLScan.io", "category": "web",
        "description": "Submit suspect URLs to a URL-scanning service for a browser-rendered report.",
        "requires_credentials": True,
        "config_fields": [
            {"key": "api_key", "label": "API key", "type": "secret", "required": True, "placeholder": "xxxx-xxxx-..."},
            {"key": "base_url", "label": "API base URL", "type": "url", "required": False, "placeholder": "https://urlscan.io/api/v1/"},
        ],
        "docs_url": "https://urlscan.io/docs/api/",
    },
]

BY_KEY = {p["key"]: p for p in CATALOG}

# Only providers with a matching sample connector in app/services/connectors can be synced.
# The sample connector emits clearly labelled SYNTHETIC data - the sync message says so.
SYNC_CONNECTORS = {
    "x_twitter": "sample-listings",
    "instagram": "sample-listings",
    "google_play": "sample-listings",
    "app_store": "sample-listings",
}

UNVERIFIED_MESSAGE = (
    "Credentials stored, but live API access could not be verified from this environment "
    "(no outbound provider access configured). Status stays 'configured — unverified'."
)

HTTP_TIMEOUT_SECONDS = 5.0
MAX_FETCH_BYTES = 512 * 1024


# ---------- helpers ----------
def catalog_spec(key: str) -> dict[str, Any]:
    spec = BY_KEY.get(key)
    if spec is None:
        raise NotFoundError(f"Unknown integration provider '{key}'")
    return spec


def _fernet():
    from app.services.crypto_utils import fernet

    # Deterministic per SECRET_KEY derivation (see crypto_utils): rotating SECRET_KEY
    # invalidates stored configs (by design).
    return fernet()


def encrypt_config(config: dict[str, Any]) -> str:
    from app.services.crypto_utils import encrypt_dict

    return encrypt_dict(config)


def decrypt_config(blob: str) -> dict[str, Any]:
    from app.services.crypto_utils import decrypt_dict

    return decrypt_dict(blob)


def _row(db: Session, actor: User, key: str) -> IntegrationConfig | None:
    stmt = select(IntegrationConfig).where(IntegrationConfig.provider_key == key)
    if actor.organization_id is None:
        stmt = stmt.where(IntegrationConfig.organization_id.is_(None))
    else:
        stmt = stmt.where(IntegrationConfig.organization_id == actor.organization_id)
    return db.scalar(stmt)


def validate_config(provider: dict[str, Any], config: dict[str, Any]) -> None:
    from app.utils.urls import parse_url

    problems: list[dict] = []
    fields = {f["key"]: f for f in provider["config_fields"]}
    for unknown in sorted(set(config) - set(fields)):
        problems.append({"field": unknown, "message": "unknown configuration field for this provider"})
    for fkey, f in fields.items():
        value = config.get(fkey)
        missing = value is None or (isinstance(value, str) and not value.strip())
        if f["required"] and missing:
            problems.append({"field": fkey, "message": "this field is required"})
            continue
        if missing:
            continue
        if not isinstance(value, str):
            problems.append({"field": fkey, "message": "must be a string"})
            continue
        if f["type"] == "secret" and len(value) < 8:
            problems.append({"field": fkey, "message": "secret values must be at least 8 characters"})
        elif f["type"] == "url" and parse_url(value) is None:
            problems.append({"field": fkey, "message": "must be a valid http(s) URL"})
        elif f["type"] == "select" and f.get("options") and value not in f["options"]:
            problems.append({"field": fkey, "message": f"must be one of: {', '.join(f['options'])}"})
    if problems:
        raise ValidationFailure("Invalid integration configuration", details=problems)


def _preview(provider: dict[str, Any], config_keys: dict[str, Any]) -> dict[str, Any]:
    """Echo of the STORED non-secret configuration only: secrets appear as '••••', never as values."""
    secret_keys = {f["key"] for f in provider["config_fields"] if f["type"] == "secret"}
    out: dict[str, Any] = {}
    for k, v in (config_keys or {}).items():
        out[k] = MASK if k in secret_keys else v
    return out


def item_dict(provider: dict[str, Any], row: IntegrationConfig | None) -> dict[str, Any]:
    out = {**provider, "status": row.status if row else "not_configured",
           "last_sync_at": row.last_sync_at if row else None, "last_error": row.last_error if row else None,
           "config_preview": _preview(provider, row.config_keys if row else {}), "connected_by": None}
    if row and row.connected_by:
        out["connected_by"] = {"id": row.connected_by.id, "email": row.connected_by.email, "full_name": row.connected_by.full_name}
    return out


def list_integrations(db: Session, actor: User) -> dict[str, Any]:
    stmt = select(IntegrationConfig)
    if actor.organization_id is None:
        stmt = stmt.where(IntegrationConfig.organization_id.is_(None))
    else:
        stmt = stmt.where(IntegrationConfig.organization_id == actor.organization_id)
    rows = {r.provider_key: r for r in db.scalars(stmt).all()}
    items = [item_dict(p, rows.get(p["key"])) for p in CATALOG]
    return {"items": items, "total": len(items)}


def get_item(db: Session, actor: User, key: str) -> dict[str, Any]:
    return item_dict(catalog_spec(key), _row(db, actor, key))


# ---------- mutations ----------
def connect(db: Session, actor: User, key: str, config: dict[str, Any]) -> dict[str, Any]:
    provider = catalog_spec(key)
    validate_config(provider, config)
    encrypted = encrypt_config(config)
    echo: dict[str, Any] = {}
    for f in provider["config_fields"]:
        if f["key"] in config and config[f["key"]] not in (None, ""):
            echo[f["key"]] = MASK if f["type"] == "secret" else config[f["key"]]
    row = _row(db, actor, key)
    if row is None:
        row = IntegrationConfig(organization_id=actor.organization_id, provider_key=key, status="configured",
                                config_encrypted=encrypted, config_keys=echo, connected_by_id=actor.id, last_error=None)
        db.add(row)
    else:
        row.status, row.config_encrypted, row.config_keys = "configured", encrypted, echo
        row.connected_by_id, row.last_error = actor.id, None
    audit.record(db, actor, "integration.connect", "integration", key,
                 details={"provider": key, "configured_fields": sorted(echo), "secrets_stored_encrypted": True})
    db.commit()
    return item_dict(provider, row)


def disconnect(db: Session, actor: User, key: str) -> dict[str, Any]:
    provider = catalog_spec(key)
    row = _row(db, actor, key)
    if row is None:
        return item_dict(provider, None)  # idempotent: already not configured
    db.delete(row)
    audit.record(db, actor, "integration.disconnect", "integration", key, details={"provider": key})
    db.commit()
    return item_dict(provider, None)


# ---------- testing (never fakes success) ----------
def _require_configured(db: Session, actor: User, key: str) -> tuple[dict, IntegrationConfig, dict]:
    provider = catalog_spec(key)
    row = _row(db, actor, key)
    if row is None or row.status == "not_configured" or not row.config_encrypted:
        raise DomainError(f"'{provider['name']}' is not configured", code="not_configured", status_code=400)
    return provider, row, decrypt_config(row.config_encrypted)


def _test_dns(config: dict[str, Any]) -> tuple[bool, str]:
    domain = (config.get("check_domain") or "example.com").strip() or "example.com"
    try:
        from app.services.url_inspector import default_resolver
        addrs = default_resolver(domain, 443)
        if not addrs:
            return False, f"DNS lookup for {domain} returned no addresses."
        return True, f"Live DNS resolution succeeded for {domain}: {', '.join(addrs[:4])} (real system resolver lookup)."
    except Exception as exc:  # honest failure - no fabrication
        return False, f"DNS resolution for {domain} failed ({type(exc).__name__}: {exc})."


def _test_web(config: dict[str, Any]) -> tuple[bool, str]:
    from app.services.url_inspector import SafeFetcher

    url = (config.get("target_url") or "").strip()
    if not url:
        return False, "No target URL configured."
    method = config.get("method") or "GET"
    try:
        result = SafeFetcher(method=method, user_agent=config.get("user_agent") or "AnaRisk-Integration-Test/1.0").fetch(url)
        size, status = result.size_bytes, result.status
        ok = status < 400
        msg = f"Real {method} request to {url} completed: HTTP {status} ({size} bytes read)."
        if not ok:
            msg += " The server returned an error status - the target may be down or blocking us."
        return ok, msg
    except DomainError as exc:
        return False, f"Real {method} request was blocked or failed ({exc.code}: {exc.message})."
    except Exception as exc:
        return False, f"Real {method} request to {url} failed ({type(exc).__name__}: {exc})."


def test_provider(db: Session, actor: User, key: str) -> dict[str, Any]:
    provider, row, config = _require_configured(db, actor, key)
    checked_at = datetime.now(UTC)
    if key == "dns_whois":
        ok, message = _test_dns(config)
    elif key == "web_scraping":
        ok, message = _test_web(config)
    else:
        # Credentials exist, but no live provider access/OAuth flow is available from this environment.
        ok, message = False, UNVERIFIED_MESSAGE
    return {"ok": ok, "message": message, "checked_at": checked_at}


# ---------- sync through the sample connector ----------
def sync(db: Session, actor: User, key: str, brand_id, query: dict[str, Any]) -> dict[str, Any]:
    from app.services.collection import run_connector

    provider, row, _config = _require_configured(db, actor, key)
    connector_key = SYNC_CONNECTORS.get(key)
    if connector_key is None:
        raise DomainError(f"No connector is available for '{provider['name']}' in this environment",
                          code="no_connector_available", status_code=400)
    if brand_id:
        brand = get_brand_for_user(db, actor, brand_id)
    else:
        brand = db.scalar(select(Brand).where(brand_scope(actor, Brand.id)).order_by(Brand.created_at).limit(1))
        if brand is None:
            raise NotFoundError("No brand in your scope to sync against")
    out = run_connector(db, actor, connector_key, brand.id, query or {})
    created = sum(1 for _, c in out if c)
    row.last_sync_at, row.last_error, row.status = datetime.now(UTC), None, "configured"
    db.commit()
    audit.record(db, actor, "integration.sync", "integration", key,
                 details={"provider": key, "connector": connector_key, "items": len(out), "created": created})
    notify_svc.notify(db, [actor.id], "integration_sync", f"{provider['name']} sync completed",
                      f"{len(out)} item(s) processed via sample connector '{connector_key}' ({created} new). "
                      "Provenance: synthetic sample data - not live provider data.",
                      link_url="/integrations", resource=("integration", None))
    db.commit()
    message = (f"Synced {len(out)} item(s) through sample connector '{connector_key}' for {provider['name']} "
               f"({created} new entit{'y' if created == 1 else 'ies'}). Data provenance: SYNTHETIC sample data "
               "generated by the demo connector - this is NOT live data from the provider.")
    return {"synced": len(out), "created_entities": created, "message": message}
