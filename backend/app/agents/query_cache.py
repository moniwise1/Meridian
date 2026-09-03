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

In-process, same limitation as app/security/rate_limit.py: not shared
across worker processes (a second worker won't see hits the first one
populated), and bounded to MAX_ENTRIES with oldest-first eviction rather
than a real LRU — adequate for a single-process MVP, not a production
cache.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict

from app.config import settings

MAX_ENTRIES = 500

_lock = threading.Lock()
_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()  # key -> (expires_at, result)


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
    with _lock:
        _cache[key] = (time.monotonic() + settings.ask_cache_ttl_seconds, result)
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)
