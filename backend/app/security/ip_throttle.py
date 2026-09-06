"""
Per-client-IP throttles for unauthenticated, cheap-but-abusable endpoints.

Right now that's just POST /auth/register (creates a tenant + first user +
a unique subdomain and fires a welcome email - none of which should be
scriptable in bulk). The per-email login cooldown covers /auth/login and
/platform/login; this covers the create-side.

Backed by the same in-process / Redis split as app/security/rate_limit.py
and login_cooldown.py - reuses that module's sliding-window limiter
classes directly rather than duplicating them.

Honest limitation: `client_ip` reads X-Forwarded-For, which a client can
forge unless every hop in front of this app is trusted. Behind a single
known proxy (Railway) the first entry is the real client; a determined
attacker rotating the header can still spread out. This is a
defence-in-depth abuse brake, not a hard boundary - the per-email login
cooldown and the auth checks themselves are the real controls.
"""
from fastapi import Request

from app.config import settings
from app.security.rate_limit import (
    _SlidingWindowLimiter, _RedisSlidingWindowLimiter, RateLimitExceeded,
)
from app.security.redis_client import get_redis_client

__all__ = ["client_ip", "check_register_rate_limit", "RateLimitExceeded"]


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _make_limiter(limit: int, window_seconds: int):
    redis = get_redis_client()
    if redis is not None:
        return _RedisSlidingWindowLimiter(redis, limit=limit, window_seconds=window_seconds)
    return _SlidingWindowLimiter(limit=limit, window_seconds=window_seconds)


_register_limiter = _make_limiter(settings.register_rate_limit_per_ip_per_hour, 3600)


def check_register_rate_limit(ip: str) -> None:
    """Raises RateLimitExceeded if this IP has registered too many times in
    the last hour."""
    _register_limiter.check(f"register:{ip}")
