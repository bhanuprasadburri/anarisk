from contextvars import ContextVar

request_ip: ContextVar[str | None] = ContextVar("request_ip", default=None)


def client_ip(x_forwarded_for: str | None, fallback: str | None, trust_proxy_headers: bool = True) -> str | None:
    """Best-effort client IP behind a reverse proxy (Render, nginx, Cloudflare, …).

    Without this, ``request.client.host`` behind a proxy is the proxy itself, which puts
    EVERY user into one shared rate-limit bucket (e.g. 10 logins/minute for the entire
    site) and stamps audit rows with the proxy's IP.

    ``X-Forwarded-For`` is client-controlled at its left end, so the LAST entry is used:
    that is the address the trusted proxy itself appended when the request arrived.
    The header is only consulted when ``trust_proxy_headers`` is enabled (set it to false
    when the service is exposed directly to the internet without a proxy in front, where
    a client could otherwise spoof its own rate-limit key).
    """
    if trust_proxy_headers and x_forwarded_for:
        parts = [p.strip() for p in x_forwarded_for.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return fallback
