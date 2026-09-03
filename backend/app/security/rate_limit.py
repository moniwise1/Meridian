"""
Rate limiting and concurrency limiting for /ask/stream.

Every question there costs a real LLM call (sometimes two — SQL generation
and insight explanation) plus a live query against a customer's database,
so it's the one endpoint where a single user or tenant could run up real
cost or DB load with no limit in place at all. This complements, rather
than duplicates, the per-query bounds that already exist:
`query_validator.py` caps every generated query's result size with an
injected `LIMIT`, and each connector enforces `query_timeout_seconds`. Those
bound the cost of *one* query; this module bounds *how many* can run.

Two independent limits:
- A sliding-window rate limit per user (`ask_rate_limit_per_user_per_minute`
  in settings) — stops one account from hammering the endpoint.
- A concurrency cap per tenant (`ask_max_concurrent_per_tenant`) — stops one
  tenant from holding an unbounded number of LLM calls / DB connections
  open at once regardless of how spread out over time they are.

Two backends behind the exact same public functions
(check_ask_rate_limit/acquire_concurrency_slot/release_concurrency_slot),
chosen once at import time based on settings.redis_url:

- In-process (REDIS_URL unset, the default): a plain dict guarded by a
  lock, held in this worker process's memory only. Correct for a single
  instance; behind multiple worker processes or replicas each one enforces
  its own independent limit, so the *effective* system-wide limit is
  (per-process limit x number of workers), not the configured number.
- Redis-backed (REDIS_URL set): genuinely global across every process and
  replica. Uses plain atomic single-command operations (ZADD/INCR/DECR),
  not Lua scripts or WATCH/MULTI transactions — see the class docstrings
  below for why that's still correct here: the worst case under real
  concurrent access is a request that briefly over-admits by one slot and
  immediately self-corrects, never a limit that stays permanently
  exceeded. A rate limiter doesn't need the linearizability a payment or
  a row-scope check would; trading a theoretical, self-healing race for
  much simpler (and thus more auditable) code is the right call here,
  and it avoids the native-Lua-interpreter dependency a fully
  Lua-scripted version would pull in. Fails open on a Redis connection
  error (see app/security/redis_client.py's docstring for why) rather
  than blocking the request or crashing.
"""
import threading
import time
import uuid
from collections import defaultdict, deque

from app.config import settings
from app.security.redis_client import get_redis_client, log_redis_failure


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(retry_after_seconds, 0.0)
        super().__init__(f"Rate limit exceeded, retry after {self.retry_after_seconds:.0f}s.")


class ConcurrencyLimitExceeded(Exception):
    pass


# ---------- In-process (default) ----------

class _SlidingWindowLimiter:
    """At most `limit` calls per `window_seconds` per key, tracked as a
    deque of call timestamps — old timestamps outside the window are
    dropped lazily on the next check for that key."""

    def __init__(self, limit: int, window_seconds: float):
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                raise RateLimitExceeded(self._window - (now - hits[0]))
            hits.append(now)


class _ConcurrencyLimiter:
    """At most `limit` concurrently in-flight calls per key."""

    def __init__(self, limit: int):
        self._limit = limit
        self._active: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def acquire(self, key: str) -> None:
        with self._lock:
            if self._active[key] >= self._limit:
                raise ConcurrencyLimitExceeded(
                    f"Too many analyses are already running for your organization "
                    f"right now (limit {self._limit} at once). Wait for one to finish "
                    f"and try again."
                )
            self._active[key] += 1

    def release(self, key: str) -> None:
        with self._lock:
            # max(0, ...) so a release without a matching acquire (shouldn't
            # happen, but this is a bookkeeping counter, not a real
            # semaphore with blocking acquire) can never go negative and
            # falsely tighten the limit for everyone after it.
            self._active[key] = max(0, self._active[key] - 1)


# ---------- Redis-backed (REDIS_URL set) ----------

class _RedisSlidingWindowLimiter:
    """Same semantics as _SlidingWindowLimiter, backed by a Redis sorted
    set per key (score = call timestamp). Pattern: always ZADD the current
    call first (unique member per call, since ZADD needs unique members —
    the score, not the member, is what matters), clean up everything
    outside the window, then ZCARD to see the true count including this
    call. If that's over the limit, ZREM the entry this call just added
    and reject. Two truly-concurrent calls landing at the same instant
    both add themselves first, so whichever one's ZCARD runs last sees
    both entries and correctly self-rejects if that pushes the count over
    — there's no window where the limit stays permanently exceeded, only
    a call that (correctly) loses a race it was really part of."""

    def __init__(self, redis_client, limit: int, window_seconds: float):
        self._redis = redis_client
        self._limit = limit
        self._window = window_seconds

    def check(self, key: str) -> None:
        import redis as redis_lib
        redis_key = f"ratelimit:{key}"
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        try:
            pipe = self._redis.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.zremrangebyscore(redis_key, 0, now - self._window)
            pipe.zcard(redis_key)
            pipe.expire(redis_key, int(self._window) + 1)
            _, _, count, _ = pipe.execute()
        except redis_lib.RedisError as e:
            log_redis_failure("ask rate limit check", e)
            return  # fail open - see module docstring

        if count > self._limit:
            try:
                self._redis.zrem(redis_key, member)
                oldest = self._redis.zrange(redis_key, 0, 0, withscores=True)
            except redis_lib.RedisError as e:
                log_redis_failure("ask rate limit rollback", e)
                oldest = []
            retry_after = self._window
            if oldest:
                retry_after = max(0.0, self._window - (now - oldest[0][1]))
            raise RateLimitExceeded(retry_after)


class _RedisConcurrencyLimiter:
    """Same semantics as _ConcurrencyLimiter, backed by a Redis counter
    per key. INCR is atomic on its own — no WATCH/Lua needed. If the
    post-increment value is over the limit, immediately DECR back down
    (release the slot this call just took) and reject; two truly-
    concurrent callers both INCR first, so whichever lands over the limit
    self-corrects immediately, same self-healing property as the rate
    limiter above. A safety-net TTL (well beyond any real analysis's
    duration) keeps a crashed process that never called release() from
    leaking a permanent slot."""

    def __init__(self, redis_client, limit: int):
        self._redis = redis_client
        self._limit = limit

    def acquire(self, key: str) -> None:
        import redis as redis_lib
        redis_key = f"concurrency:{key}"
        try:
            current = self._redis.incr(redis_key)
            self._redis.expire(redis_key, 3600)
        except redis_lib.RedisError as e:
            log_redis_failure("ask concurrency acquire", e)
            return  # fail open

        if current > self._limit:
            try:
                self._redis.decr(redis_key)
            except redis_lib.RedisError as e:
                log_redis_failure("ask concurrency rollback", e)
            raise ConcurrencyLimitExceeded(
                f"Too many analyses are already running for your organization "
                f"right now (limit {self._limit} at once). Wait for one to finish "
                f"and try again."
            )

    def release(self, key: str) -> None:
        import redis as redis_lib
        redis_key = f"concurrency:{key}"
        try:
            new_val = self._redis.decr(redis_key)
            if new_val < 0:
                # Clamp, matching the in-process max(0, ...) behavior -
                # shouldn't happen (a release without a matching acquire),
                # but never let it go negative and falsely tighten the
                # limit for the next caller.
                self._redis.set(redis_key, 0)
        except redis_lib.RedisError as e:
            log_redis_failure("ask concurrency release", e)


_redis = get_redis_client()
if _redis is not None:
    _user_rate_limiter = _RedisSlidingWindowLimiter(
        _redis, limit=settings.ask_rate_limit_per_user_per_minute, window_seconds=60,
    )
    _tenant_concurrency_limiter = _RedisConcurrencyLimiter(
        _redis, limit=settings.ask_max_concurrent_per_tenant,
    )
else:
    _user_rate_limiter = _SlidingWindowLimiter(
        limit=settings.ask_rate_limit_per_user_per_minute, window_seconds=60,
    )
    _tenant_concurrency_limiter = _ConcurrencyLimiter(
        limit=settings.ask_max_concurrent_per_tenant,
    )


def check_ask_rate_limit(user_id: str) -> None:
    _user_rate_limiter.check(user_id)


def acquire_concurrency_slot(tenant_id: str) -> None:
    _tenant_concurrency_limiter.acquire(tenant_id)


def release_concurrency_slot(tenant_id: str) -> None:
    _tenant_concurrency_limiter.release(tenant_id)
