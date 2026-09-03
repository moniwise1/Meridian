"""
Shared Redis client for everything that was in-process-only before this:
rate_limit.py (Ask rate/concurrency limits), login_cooldown.py, and
query_cache.py. All three exist to bound cost/abuse across every request
this app serves, which only actually works if "every request" means every
worker process and every replica, not just the one that happened to
handle a given HTTP request - that's exactly what was missing without
this. One client, one place to configure it.

Deliberately opt-in (REDIS_URL unset by default): every caller in this
app falls back to its original in-process behavior when this returns
None, so a plain `pip install -r requirements.txt` dev setup with no
Redis running keeps working exactly as before - nobody is forced to stand
up Redis just to run the app locally.

Fail-open on a Redis connection error, deliberately: a rate limiter, a
login cooldown, and a result cache are all secondary protections layered
on top of the real security boundary (auth, tenant scoping, subscription
gating - none of which touch Redis at all). If Redis itself is briefly
unreachable, the correct behavior is "this one check is skipped, log it
and move on" - not "the whole app goes down because a cache hiccupped",
which would make Redis a single point of failure for a system that works
perfectly well without it. Each caller wraps its own Redis calls in a
try/except (redis.RedisError) and does the safe default for that specific
operation - allow the request, skip the cooldown, treat as a cache miss -
rather than trying to fall back to a whole separate in-process shadow
system on every hiccup, which would be a lot of extra complexity for a
rare, transient failure mode.
"""
import logging

from app.config import settings

logger = logging.getLogger("meridian.redis")

_client = None
_client_initialized = False


def get_redis_client():
    """Returns a shared redis.Redis client, or None if REDIS_URL isn't
    set. Lazily constructed on first call (not at import time) so tests
    can set settings.redis_url before anything touches this module, and
    so importing this module never requires the `redis` package to be
    installed unless it's actually going to be used."""
    global _client, _client_initialized
    if not _client_initialized:
        _client_initialized = True
        if settings.redis_url:
            import redis as redis_lib
            # redis-py retries a connection/timeout error by default even
            # with no explicit retry config requested - discovered by this
            # module's own fail-open test taking ~15s to give up instead
            # of the ~1-2s the socket timeouts below suggest, because the
            # default Retry object was quietly retrying underneath them.
            # Every caller in this app treats a Redis failure as "skip
            # this one check, fail open" specifically so an outage never
            # turns into a slow or hung request - retries=0 is what
            # actually makes that fast rather than just eventually true.
            _client = redis_lib.Redis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
                retry=redis_lib.retry.Retry(backoff=redis_lib.backoff.NoBackoff(), retries=0),
            )
    return _client


def log_redis_failure(operation: str, error: Exception) -> None:
    logger.warning("Redis unavailable during %s, failing open: %s", operation, error)
