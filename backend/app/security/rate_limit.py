"""
In-process rate limiting and concurrency limiting for /ask/stream.

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

Honest limitation: this state is a plain dict guarded by a lock, held in
this worker process's memory — it is not shared across processes. Behind
multiple worker processes or replicas, each one enforces its own
independent limit, so the *effective* system-wide limit is
(per-process limit x number of workers), not the configured number. A real
multi-process deployment needs a shared store (Redis, or the metadata DB
itself) for this to be a genuine global limit — not implemented here, same
category of gap the README already calls out for other pieces of this app.
"""
import threading
import time
from collections import defaultdict, deque

from app.config import settings


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(retry_after_seconds, 0.0)
        super().__init__(f"Rate limit exceeded, retry after {self.retry_after_seconds:.0f}s.")


class ConcurrencyLimitExceeded(Exception):
    pass


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
