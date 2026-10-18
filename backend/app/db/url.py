"""Database URL normalisation for deployment portability.

Postgres providers hand out connection strings in several shapes. This project ships
**psycopg 3 only** (``requirements.txt``), so the common shapes fail at runtime:

===========================  ===============================================  =========================
Given URL                    What SQLAlchemy 2 does                          Result
===========================  ===============================================  =========================
``postgres://…``             raises ``NoSuchModuleError`` at engine creation   every DB request → 500
``postgresql://…``           defaults to psycopg2 → ``ModuleNotFoundError``    every DB request → 500
``postgresql+psycopg2://…``  ``ModuleNotFoundError: psycopg2`` on connect      every DB request → 500
``postgresql+psycopg://…``   works (psycopg 3)                                OK
===========================  ===============================================  =========================

Because ``/api/v1/health`` never touches the database, a service configured with any of
the broken shapes still passes its health check — "deploy succeeded, but login returns
500". :func:`normalize_database_url` coerces every legacy form to ``postgresql+psycopg://``
so the exact URL Render publishes in the dashboard works as-is.

It is idempotent, never alters credentials or the query string, and — only for hosts that
require TLS (Render) — adds ``sslmode=require`` when the URL does not already specify one.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode

log = logging.getLogger(__name__)

# scheme -> canonical scheme (psycopg 3 driver). Any other dialect is left untouched.
_SCHEME_ALIASES: dict[str, str] = {
    "postgres": "postgresql+psycopg",
    "postgresql": "postgresql+psycopg",
    "postgresql+psycopg2": "postgresql+psycopg",
    "postgresql+psycopg2binary": "postgresql+psycopg",
}

# Render Postgres refuses non-TLS connections; these hosts get sslmode=require when the
# operator did not already specify an sslmode (a provided value always wins).
_TLS_REQUIRED_HOST_SUFFIXES = (".render.com",)


def normalize_database_url(url: str) -> str:
    """Return a psycopg 3-compatible, deployment-safe form of *url* (idempotent).

    Never raises: unrecognised values (sqlite, other dialects, malformed strings) are
    returned unchanged so non-Postgres setups and tests keep working. Only the scheme
    change is logged — credentials and host never appear in log output.
    """
    if not isinstance(url, str) or "://" not in url:
        return url
    scheme, _, rest = url.partition("://")
    canonical = _SCHEME_ALIASES.get(scheme.lower())
    if canonical is None:
        return url  # not a Postgres URL this build manages (sqlite:///, etc.)
    new_rest = _ensure_tls(rest)
    if new_rest != rest and canonical == scheme:
        return f"{scheme}://{new_rest}"
    if new_rest != rest:
        log.warning(
            "DATABASE_URL host requires TLS; adding sslmode=require (no sslmode was specified)."
        )
    if canonical != scheme:
        log.warning(
            "DATABASE_URL scheme '%s://' is not usable with this build (psycopg 3 only); "
            "using '%s://' instead. Credentials and host were not modified.",
            scheme, canonical,
        )
    return f"{canonical}://{new_rest}"


def _ensure_tls(rest: str) -> str:
    """Add ``sslmode=require`` for TLS-required hosts when no sslmode was provided."""
    if "sslmode=" in rest.lower():
        return rest
    netloc, sep, path_query = rest.partition("/")
    host = netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    if not any(host.endswith(suffix) for suffix in _TLS_REQUIRED_HOST_SUFFIXES):
        return rest
    path, _, query = path_query.partition("?")
    params = dict(parse_qsl(query, keep_blank_values=True))
    params["sslmode"] = "require"
    suffix = f"?{urlencode(params)}"
    return f"{netloc}/{path}{suffix}" if sep else f"{netloc}{suffix}"
