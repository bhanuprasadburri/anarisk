"""SSRF-safe, opt-in URL inspection.

Defences (all enforced for the initial URL AND every redirect hop):
  * feature flag URL_FETCH_ENABLED (off by default) and optional registrable-domain allowlist
  * scheme limited to http/https, ports limited to 80/443, no userinfo in the URL
  * hostname resolved by us; ALL resolved addresses must be public (loopback, private, link-local, multicast,
    reserved, CGNAT, unspecified, IPv4-mapped/NAT64/6to4 wrappers of those are blocked)
  * the connection is made to the validated IP (pinned) with the original Host/SNI, defeating DNS rebinding
  * redirects handled manually (limit 3), no cookies, no auth headers forwarded
  * strict timeout, response-size cap, Accept-Encoding: identity, body is NEVER executed or rendered; only
    status, headers subset, size, sha256 and a text <title> are kept (treated as untrusted data)
"""
from __future__ import annotations

import hashlib
import html
import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin

from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.utils.urls import ParsedUrl, parse_url

_EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "240.0.0.0/4", "64:ff9b::/96", "2002::/16", "100::/64", "2001:db8::/32",
)]
_BLOCKED_NAMES = ("localhost", "localhost.localdomain")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home", ".corp", ".private")


class SsrfBlocked(DomainError):
    status_code = 422
    code = "ssrf_blocked"


class UrlFetchDisabled(DomainError):
    status_code = 409
    code = "url_fetch_disabled"


def is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version)


def default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


@dataclass
class Target:
    parsed: ParsedUrl
    port: int
    ip: str


@dataclass
class FetchResult:
    final_url: str
    status: int
    content_type: str | None
    size_bytes: int
    truncated: bool
    sha256: str
    title: str | None
    redirects: list[str] = field(default_factory=list)
    server_header: str | None = None
    elapsed_ms: int = 0


def validate_destination(url: str, *, settings: Settings | None = None, resolver: Callable[[str, int], list[str]] | None = None,
                         ip_blocker: Callable[[str], bool] = is_blocked_ip) -> Target:
    s = settings or get_settings()
    resolver = resolver or default_resolver
    p = parse_url(url, default_scheme="https")
    if p is None:
        raise SsrfBlocked("URL is not a valid http(s) URL")
    if p.has_userinfo:
        raise SsrfBlocked("URLs with embedded credentials are not allowed")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in s.url_fetch_allowed_ports:
        raise SsrfBlocked(f"Port {port} is not allowed")
    host = p.host
    if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise SsrfBlocked("Destination host is not allowed")
    if s.url_fetch_domain_allowlist and p.registrable_domain not in {d.lower() for d in s.url_fetch_domain_allowlist}:
        raise SsrfBlocked("Destination domain is not on the allowlist")
    if p.is_ip:
        ips = [host]
    else:
        try:
            ips = resolver(host, port)
        except OSError:
            raise SsrfBlocked("Destination host could not be resolved")
    if not ips:
        raise SsrfBlocked("Destination host could not be resolved")
    if any(ip_blocker(ip) for ip in ips):  # ANY non-public answer rejects the whole name (mixed-answer rebinding)
        raise SsrfBlocked("Destination resolves to a private, loopback, link-local or otherwise non-public address")
    return Target(p, port, ips[0])


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # SNI + cert check use the hostname


class SafeFetcher:
    def __init__(self, settings: Settings | None = None, resolver=None, ip_blocker: Callable[[str], bool] = is_blocked_ip):
        self.s = settings or get_settings()
        self.resolver = resolver
        self.ip_blocker = ip_blocker

    def _request(self, target: Target, deadline: float):
        """One bounded GET. Returns (status, headers, body_bytes, truncated). Overridable in tests."""
        p, s = target.parsed, self.s
        timeout = max(0.1, min(s.url_fetch_timeout_seconds, deadline - time.monotonic()))
        cls = _PinnedHTTPS if p.scheme == "https" else _PinnedHTTP
        conn = cls(p.host, target.port, target.ip, timeout)
        try:
            path = (p.path or "/") + (f"?{p.query}" if p.query else "")
            conn.request("GET", path, headers={"User-Agent": "AnaRisk-DRP-Inspector/1.0", "Accept": "text/html,*/*;q=0.5", "Accept-Encoding": "identity", "Connection": "close"})
            resp = conn.getresponse()
            body, truncated = b"", False
            while True:
                if time.monotonic() > deadline:
                    truncated = True
                    break
                chunk = resp.read(8192)
                if not chunk:
                    break
                body += chunk
                if len(body) > s.url_fetch_max_bytes:
                    body, truncated = body[: s.url_fetch_max_bytes], True
                    break
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body, truncated
        finally:
            conn.close()

    def fetch(self, url: str) -> FetchResult:
        s = self.s
        if not s.url_fetch_enabled:
            raise UrlFetchDisabled("Outbound URL inspection is disabled (set URL_FETCH_ENABLED=true behind an egress firewall)")
        started = time.monotonic()
        deadline = started + s.url_fetch_timeout_seconds * 2
        redirects: list[str] = []
        current = url
        for hop in range(s.url_fetch_max_redirects + 1):
            target = validate_destination(current, settings=s, resolver=self.resolver, ip_blocker=self.ip_blocker)
            try:
                status, headers, body, truncated = self._request(target, deadline)
            except (OSError, http.client.HTTPException) as exc:
                raise DomainError(f"Could not fetch URL ({type(exc).__name__})", code="fetch_failed", status_code=502)
            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                if hop >= s.url_fetch_max_redirects:
                    raise SsrfBlocked("Too many redirects")
                current = urljoin(target.parsed.canonical, headers["location"])
                redirects.append(current)
                continue  # next loop iteration re-validates the redirect target
            m = re.search(rb"(?is)<title[^>]*>(.{0,300}?)</title>", body[:65536])
            title = html.unescape(m.group(1).decode("utf-8", "replace")).strip()[:200] if m else None
            return FetchResult(
                final_url=target.parsed.canonical, status=status, content_type=(headers.get("content-type") or "")[:100] or None,
                size_bytes=len(body), truncated=truncated, sha256=hashlib.sha256(body).hexdigest(), title=title, redirects=redirects,
                server_header=(headers.get("server") or "")[:100] or None, elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        raise SsrfBlocked("Too many redirects")
