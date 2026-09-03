"""
Hash-chained audit logging (BUILD SPEC section 27).

Never pass secrets, tokens, or raw row-level data into `detail` — callers
are responsible for only passing structural facts (row counts, table names,
query ids), never cell values.

Each entry's `entry_hash` covers its own fields plus the previous entry's
hash (`prev_hash`), scoped per tenant. Editing or deleting a row - or
inserting one out of band, bypassing this module - breaks the chain from
that point forward, and `verify_chain()` below detects exactly where.

Be precise about what this buys you: it's tamper-*evidence*, not
tamper-*proofing*. The hash algorithm lives in this file, in the same
database and codebase it's protecting. Someone with DB write access and
knowledge of this code could rewrite a run of rows and recompute every hash
after them consistently, and verification would find nothing wrong. What it
does catch is anything short of that — an accidental edit, a bug elsewhere
writing to this table directly, a careless/partial tamper attempt, or plain
corruption. A genuinely tamper-proof trail needs the chain's head hash
anchored somewhere outside this database entirely (a separate write-once
log, an external timestamping service) - not implemented here.

Also worth flagging: `log()` looks up the current chain head with a plain
query, not a locking read. Two concurrent requests logging at nearly the
same instant could both read the same head and each append a row pointing
at it, forking the chain rather than serializing it. Fine for this
single-writer-in-practice MVP; a real deployment under concurrent load
would need the lookup-and-append to happen inside one serialized
transaction (e.g. `SELECT ... FOR UPDATE` on a per-tenant chain-head row).
"""
import hashlib
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.models import AuditLog

_FORBIDDEN_DETAIL_KEYS = {"password", "token", "api_key", "secret", "credential"}
GENESIS_HASH = "0" * 64


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, tenant_id: str, user_id: str | None, timestamp: datetime,
                   action: str, connection_id: str | None, query_id: str | None,
                   detail: dict, status: str) -> str:
    payload = {
        "prev_hash": prev_hash,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "timestamp": timestamp.isoformat(),
        "action": action,
        "connection_id": connection_id,
        "query_id": query_id,
        "detail": detail,
        "status": status,
    }
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def log(db: Session, tenant_id: str, action: str, user_id: str | None = None,
        connection_id: str | None = None, query_id: str | None = None,
        detail: dict | None = None, status: str = "ok") -> None:
    detail = detail or {}
    safe_detail = {k: v for k, v in detail.items() if k.lower() not in _FORBIDDEN_DETAIL_KEYS}

    prev = (
        db.query(AuditLog)
        .filter_by(tenant_id=tenant_id)
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    prev_hash = prev.entry_hash if prev else GENESIS_HASH
    timestamp = datetime.utcnow()
    entry_hash = _compute_hash(prev_hash, tenant_id, user_id, timestamp, action,
                                connection_id, query_id, safe_detail, status)

    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        timestamp=timestamp,
        action=action,
        connection_id=connection_id,
        query_id=query_id,
        detail=safe_detail,
        status=status,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    db.add(entry)
    db.commit()


def verify_chain(db: Session, tenant_id: str) -> dict:
    """Recomputes the hash chain for this tenant's audit log from scratch
    and reports the first point where it doesn't match what's stored. See
    the module docstring for exactly what this does and doesn't guarantee."""
    rows = (
        db.query(AuditLog)
        .filter_by(tenant_id=tenant_id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )
    expected_prev = GENESIS_HASH
    for row in rows:
        if row.prev_hash != expected_prev:
            return {
                "intact": False, "checked": len(rows), "broken_at": row.id,
                "reason": "This entry's prev_hash doesn't match the chain — "
                          "a row may be missing, reordered, or inserted out of band.",
            }
        recomputed = _compute_hash(row.prev_hash, row.tenant_id, row.user_id, row.timestamp,
                                    row.action, row.connection_id, row.query_id, row.detail, row.status)
        if recomputed != row.entry_hash:
            return {
                "intact": False, "checked": len(rows), "broken_at": row.id,
                "reason": "This entry's own content doesn't match its stored hash — "
                          "it was modified after being written.",
            }
        expected_prev = row.entry_hash
    return {"intact": True, "checked": len(rows), "broken_at": None, "reason": ""}
