"""Shared URL normalization and lexical features for offline training and inference."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from app.utils.urls import registrable_domain

MAX_URL_CHARS = 25_000
FEATURE_VERSION = "url-lexical-v1"
FEATURE_NAMES = (
    "url_length", "host_length", "path_length", "query_length", "subdomain_count", "label_count",
    "has_ip_host", "has_punycode", "https", "at_count", "hyphen_count", "digit_ratio",
    "dot_count", "encoded_count", "suspicious_token_count",
)


def normalize_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value or len(value) > MAX_URL_CHARS or any(ord(c) < 32 for c in value):
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if not host or len(host) > 253:
            return ""
        port = parsed.port
        netloc = host + (f":{port}" if port and port not in (80, 443) else "")
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        return ""


def features(url: str) -> tuple[float, ...]:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    labels = [x for x in host.split(".") if x]
    text = f"{host}{parsed.path}?{parsed.query}"
    lowered = text.lower()
    return (
        min(len(url), 5000) / 5000, min(len(host), 253) / 253,
        min(len(parsed.path), 2000) / 2000, min(len(parsed.query), 2000) / 2000,
        min(max(0, len(labels) - 2), 10) / 10, min(len(labels), 15) / 15,
        float(all(c.isdigit() or c == "." for c in host) and bool(host)), float("xn--" in host),
        float(parsed.scheme == "https"), min(url.count("@"), 5) / 5,
        min(host.count("-"), 20) / 20, sum(c.isdigit() for c in host) / max(1, len(host)),
        min(host.count("."), 10) / 10, min(lowered.count("%"), 20) / 20,
        min(sum(lowered.count(t) for t in ("login", "verify", "secure", "account", "update", "password", "signin")), 10) / 10,
    )


def group_key(url: str) -> str:
    return registrable_domain((urlsplit(url).hostname or "").lower().rstrip("."))
