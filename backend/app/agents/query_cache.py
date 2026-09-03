"""
Result cache for repeated identical questions (query cost control /
caching). An identical question asked twice — two analysts curious about
the same headline metric, a demo re-run, a dashboard-style recurring
question — currently re-runs the full SQL-generation LLM call, a live query
against the customer's database, and the insight-explanation LLM call, all
over again. This lets an exact repeat skip straight to the answer.

Deliberately scoped to *fresh* questions only (`conversation_id is None`).
A follow-up's meaning depends on the evolving conversation context, so
caching one correctly would mean folding that whole context into the cache
key; simpler and safer to just never cache follow-ups than to get that
subtly wrong and serve a stale or mismatched answer.

The cache key is the security-sensitive part, so it's deliberately
over-inclusive rather than under-inclusive:
- The connection's *current* `table_allowlist`/`column_policy`, not just
  its id — if an admin tightens policy between two identical questions, the
  key changes and the old (now over-permissive) cached entry becomes
  unreachable rather than being served past the policy change.
- The caller's `row_scope` — two users asking the identical question under
  different row-level restrictions never share a cache entry.
Get either of those wrong and this cache becomes a way to read data a
policy change or a row-scope restriction was supposed to block. Both are
included on every lookup and every write.

Two backends behind the exact same public functions (get/put), chosen
once at import time based on settings.redis_url — same split as
app/security/rate_limit.py and login_cooldown.py:

- In-process (REDIS_URL unset, the default): not shared across worker
  processes (a second worker won't see hits the first one populated), and
  bounded to MAX_ENTRIES with oldest-first eviction rather than a real
  LRU — adequate for a single-process MVP, not a production cache.
- Redis-backed (REDIS_URL set): genuinely shared across every process and
  replica, so a second worker (or a second instance entirely) DOES see a
  hit the first one populated — the whole point of a cache is defeated
  if each process keeps its own. No MAX_ENTRIES/eviction logic needed:
  every entry carries its own TTL (ask_cache_ttl_seconds) via Redis's own
  EX, so expiry is Redis's job, not this module's; size the Redis
  instance for the traffic instead of replicating an eviction policy here.
  Cache misses fail open on a Redis connection error (see
  app/security/redis_client.py's docstring) — a miss just means a fresh
  (slower, more expensive) computation runs, never an error surfaced to
  the caller, so there's nothing unsafe about that fallback.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict

from app.config import settings
from app.security.redis_client import get_redis_client, log_redis_failure

MAX_ENTRIES = 500

_lock = threading.Lock()
_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()  # key -> (expires_at, result)
_redis = get_redis_client()


def _cache_key(tenant_id: str, connection_id: str, table_allowlist: list[str] | None,
               column_policy: dict | None, row_scope: dict | None, question: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        "connection_id": connection_id,
        "table_allowlist": sorted(table_allowlist or []),
        "column_policy": {k: sorted(v) for k, v in sorted((column_policy or {}).items())},
        "row_scope": {k: sorted(v) for k, v in sorted((row_scope or {}).items())},
        "question": question.strip(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def get(tenant_id: str, connection_id: str, table_allowlist: list[str] | None,
        column_policy: dict | None, row_scope: dict | None, question: str) -> dict | None:
    key = _cache_key(tenant_id, connection_id, table_allowlist, column_policy, row_scope, question)

    if _redis is not None:
        import redis as redis_lib
        try:
            raw = _redis.get(f"querycache:{key}")
        except redis_lib.RedisError as e:
            log_redis_failure("query cache get", e)
            return None  # fail open - treat as a miss
        return json.loads(raw) if raw is not None else None

    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, result = entry
        if time.monotonic() > expires_at:
            del _cache[key]
            return None
        _cache.move_to_end(key)  # recently-hit entries survive eviction longer
        return result


def put(tenant_id: str, connection_id: str, table_allowlist: list[str] | None,
        column_policy: dict | None, row_scope: dict | None, question: str, result: dict) -> None:
    key = _cache_key(tenant_id, connection_id, table_allowlist, column_policy, row_scope, question)

    if _redis is not None:
        import redis as redis_lib
        try:
            _redis.set(f"querycache:{key}", json.dumps(result, default=str), ex=settings.ask_cache_ttl_seconds)
        except redis_lib.RedisError as e:
            log_redis_failure("query cache put", e)
        return

    with _lock:
        _cache[key] = (time.monotonic() + settings.ask_cache_ttl_seconds, result)
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)
