"""Website / link scanner (passive-first).

Passive checks (always available): URL canonicalisation, DNS resolution with private-address
rejection, TLS certificate inspection (issuer, hostname, validity window), SPF/DMARC, lookalike
analysis against workspace official domains, and offline URL heuristics.

Live fetching only happens when ``URL_FETCH_ENABLED=true`` (the SSRF-guarded SafeFetcher
validates every hop and pins the connection to the validated IP). When fetching is disabled
the result says so explicitly - it never pretends a fetch occurred.
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import ssl
from typing import Any

from app.core.config import get_settings
from app.services.tools.common import (
    Finding, check_spf_and_dmarc, dns_query, domain_lookalike_check, url_heuristic_check,
)
from app.utils.urls import from_idna, parse_url, registrable_domain


def _resolve_host(host: str) -> tuple[list[str] | None, str | None]:
    try:
        from app.services.url_inspector import default_resolver
        ips = sorted(default_resolver(host, 443))
        return ips, None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def dns_resolution_check(host: str) -> tuple[Finding, list[str]]:
    ips, err = _resolve_host(host)
    if err:
        return Finding(
            check="dns_resolution", title="DNS resolution", status="unable_to_verify", severity="unknown",
            summary=f"Could not resolve {host} - it does not resolve right now (or DNS is unavailable).",
            evidence=[f"resolution failed: {err}"], source="System resolver",
            limitation="A failed resolution is not proof the domain is malicious; it may simply not exist.",
        ), []
    blocked = [ip for ip in ips if _is_non_public(ip)]
    if blocked:
        return Finding(
            check="dns_resolution", title="DNS resolution", status="suspicious", severity="high",
            summary=f"{host} resolves to non-public address(es) ({', '.join(blocked)}).",
            evidence=[f"addresses: {', '.join(ips)}"],
            source="System resolver",
            limitation="Non-public targets are typical of internal/phishing kit setups; also used legitimately behind split DNS.",
        ), ips
    return Finding(
        check="dns_resolution", title="DNS resolution", status="verified", severity="none",
        summary=f"{host} resolves to {len(ips)} public address(es).",
        evidence=[f"addresses: {', '.join(ips[:6])}"], source="System resolver",
        limitation="Resolution confirms the domain exists; it says nothing about who operates it.",
    ), ips


def _is_non_public(ip_str: str) -> bool:
    from app.services.url_inspector import is_blocked_ip

    try:
        return bool(is_blocked_ip(ip_str)) or not ipaddress.ip_address(ip_str).is_global
    except ValueError:
        return True


def tls_certificate_check(host: str, port: int = 443) -> Finding:
    """Inspect the TLS certificate presented for `host` without sending any HTTP request."""
    try:
        from app.services.url_inspector import default_resolver
        addresses = default_resolver(host, port)
        if not addresses:
            raise OSError("DNS lookup returned no addresses")
        target_ip = sorted(addresses, key=lambda a: 0 if ":" not in a else 1)[0]
        if _is_non_public(target_ip):
            return Finding(
                check="tls_certificate", title="TLS certificate", status="unable_to_verify", severity="unknown",
                summary="Certificate inspection skipped: the host resolves to a non-public address.",
                evidence=[f"target: {target_ip}"], source="System resolver policy",
                limitation="Refusing to connect to non-public addresses (SSRF protection).",
            )
        ctx = ssl.create_default_context()
        with socket.create_connection((target_ip, port), timeout=5.0) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                cipher = tls.cipher()
    except ssl.SSLCertVerificationError as exc:
        return Finding(
            check="tls_certificate", title="TLS certificate", status="suspicious", severity="high",
            summary=f"The TLS certificate for {host} failed verification: {exc.verify_message}.",
            evidence=[f"error: {exc.verify_error}"], source="TLS handshake",
            limitation="Expired/self-signed certificates are common on both malicious and freshly-provisioned legitimate sites.",
        )
    except (OSError, ssl.SSLError) as exc:
        return Finding(
            check="tls_certificate", title="TLS certificate", status="unable_to_verify", severity="unknown",
            summary=f"Could not complete a TLS handshake with {host}:443.",
            evidence=[f"error: {type(exc).__name__}: {exc}"], source="TLS handshake",
            limitation="No HTTPS service could be reached; the site may be HTTP-only or blocking connections.",
        )
    subject = dict(x[0] for x in cert.get("subject", ()))
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    sans = [v for k, v in cert.get("subjectAltName", ())]
    not_after = cert.get("notAfter")
    not_before = cert.get("notBefore")
    expiry = None
    days_left = None
    if not_after:
        expiry = _dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=_dt.timezone.utc)
        days_left = (expiry - _dt.datetime.now(_dt.timezone.utc)).days
    hostname_ok = bool(san_match(subject.get("commonName", ""), sans, host))
    evidence = [
        f"subject CN: {subject.get('commonName', '?')}",
        f"issuer: {issuer.get('organizationName', '?')} {issuer.get('commonName', '')}".strip(),
        f"validity: {not_before} → {not_after} ({days_left if days_left is not None else '?'} days left)",
        f"SANs: {', '.join(sans[:6])}",
        f"cipher: {cipher[0] if cipher else '?'}",
    ]
    if days_left is not None and days_left < 0:
        return Finding(
            check="tls_certificate", title="TLS certificate", status="suspicious", severity="high",
            summary=f"The certificate for {host} EXPIRED {abs(days_left)} day(s) ago.", evidence=evidence,
            source="TLS handshake", limitation="Expired certificates also appear on abandoned legitimate sites.",
        )
    if not hostname_ok:
        return Finding(
            check="tls_certificate", title="TLS certificate", status="suspicious", severity="high",
            summary=f"The certificate presented for {host} does not cover that hostname.",
            evidence=evidence, source="TLS handshake",
            limitation="Shared hosting/SNI mismatches can also cause this on legitimate infrastructure.",
        )
    return Finding(
        check="tls_certificate", title="TLS certificate", status="verified", severity="none",
        summary=f"Valid TLS certificate from {issuer.get('organizationName', 'an unknown CA')} "
                f"covering {host} ({days_left} days remaining).",
        evidence=evidence, source="TLS handshake",
        limitation="Certificates are cheap; a valid certificate does not imply a trustworthy site.",
    )


def san_match(cn: str, sans: list[str], host: str) -> bool:
    names = ([cn] if cn else []) + sans
    h = host.lower()
    for name in names:
        n = name.lower()
        if n.startswith("*.") and (h.endswith(n[1:]) and h.count(".") == n.count(".")):
            return True
        if n == h:
            return True
    return False


def analyze_url(payload: dict[str, Any], official_domains: list[str]) -> tuple[str, list[Finding]]:
    findings: list[Finding] = []
    raw = (payload.get("url") or "").strip()
    parsed = parse_url(raw)
    if parsed is None:
        findings.append(Finding(
            check="url_canonicalisation", title="URL validation", status="unable_to_verify", severity="unknown",
            summary="The submitted value is not a valid http(s) URL.",
            evidence=[f"input: {raw[:200]}"], source="URL parser", limitation="Provide a full http(s) URL.",
        ))
        return raw[:80] or "URL analysis", findings
    findings.append(Finding(
        check="url_canonicalisation", title="URL canonicalisation", status="verified", severity="none",
        summary=f"Canonical form: {parsed.canonical}",
        evidence=[f"host: {parsed.host}", f"registrable domain: {parsed.registrable_domain}",
                  f"scheme: {parsed.scheme}", f"port: {parsed.port or 'default'}"],
        source="URL parser", limitation="Canonicalisation is deterministic and offline.",
    ))
    findings.append(url_heuristic_check(raw, official_domains))
    res_finding, _ips = dns_resolution_check(parsed.host)
    findings.append(res_finding)
    if parsed.scheme == "https":
        findings.append(tls_certificate_check(parsed.host))
    else:
        findings.append(Finding(
            check="tls_certificate", title="TLS certificate", status="inconclusive", severity="low",
            summary="The URL uses unencrypted http:// - no TLS certificate to inspect.",
            evidence=[f"scheme: {parsed.scheme}"], source="URL parser",
            limitation="Plaintext HTTP cannot protect credentials or session cookies.",
        ))
    findings.append(domain_lookalike_check(parsed.host, official_domains))
    findings.extend(check_spf_and_dmarc(parsed.registrable_domain))

    # Optional live fetch (SSRF-guarded) - only when explicitly enabled.
    s = get_settings()
    if s.url_fetch_enabled:
        from app.services.url_inspector import FetchResult, SafeFetcher, SsrfBlocked, UrlFetchDisabled

        try:
            result: FetchResult = SafeFetcher().fetch(parsed.original)
            findings.append(Finding(
                check="live_fetch", title="Live fetch", status="verified", severity="none",
                summary=f"Fetched {result.final_url} → HTTP {result.status}"
                        + (f", title “{result.title}”" if result.title else "")
                        + (f" ({len(result.redirects)} redirect hop(s))" if result.redirects else "") + ".",
                evidence=[f"status: {result.status}", f"server: {result.server_header or '?'}",
                          f"size: {result.size_bytes} B", f"sha256: {result.sha256[:16]}…"]
                         + [f"redirect: {u}" for u in result.redirects],
                source="SSRF-guarded live fetch",
                limitation="A fetched page is not executed; JavaScript and forms are never run.",
            ))
        except UrlFetchDisabled:
            pass
        except (SsrfBlocked, Exception) as exc:  # noqa: BLE001 - report honestly, never crash the tool
            findings.append(Finding(
                check="live_fetch", title="Live fetch", status="inconclusive", severity="low",
                summary=f"The live fetch was blocked or failed: {type(exc).__name__}.",
                evidence=[str(exc)[:300]], source="SSRF-guarded live fetch",
                limitation="Passive results above still apply.",
            ))
    else:
        findings.append(Finding(
            check="live_fetch", title="Live fetch", status="unable_to_verify", severity="unknown",
            summary="Live fetching is disabled on this deployment - no HTTP request was made to the target.",
            evidence=["URL_FETCH_ENABLED=false"], source="Configuration",
            limitation="Enable URL_FETCH_ENABLED=true (behind an egress firewall) for redirect-chain and page-title inspection.",
        ))

    return parsed.canonical[:80], findings
