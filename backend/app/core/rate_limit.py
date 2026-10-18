"""Small in-memory sliding-window rate limiter (per client IP + bucket).

Per-process only: behind multiple workers/instances use a shared store (e.g. Redis) or an API gateway.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

from app.core.config import get_settings

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def rate_limit(bucket: str, setting_name: str):
    def dep(request: Request):
        s = get_settings()
        if not s.rate_limit_enabled:
            return
        limit = getattr(s, setting_name)
        from app.core.context import client_ip

        ip = client_ip(
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
            s.trust_proxy_headers,
        ) or "unknown"
        key, now = f"{bucket}:{ip}", time.monotonic()
        with _lock:
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(60 - (now - q[0])))
                raise HTTPException(status_code=429, detail="Too many requests; slow down", headers={"Retry-After": str(retry)})
            q.append(now)

    return dep
