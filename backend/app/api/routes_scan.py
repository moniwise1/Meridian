"""
Risk scan endpoint — "give me the top five risks" / "find anything unusual
across everything", proactively, rather than anomaly detection only ever
running against the current question's result. See app/agents/risk_scan.py
for how the scan itself works and why it needs no LLM calls.

Reuses the exact same rate/concurrency limiting as /ask/stream
(app/security/rate_limit.py) — a scan is, if anything, more expensive than
a single question (it runs one query per table, up to MAX_TABLES_SCANNED),
so it shouldn't get a free pass around the same limits.
"""
import json
from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User, DataSourceConnection
from app.security.auth import get_current_user, require_active_subscription, AuthContext
from app.security.rate_limit import (
    check_ask_rate_limit, acquire_concurrency_slot, release_concurrency_slot,
    RateLimitExceeded, ConcurrencyLimitExceeded,
)
from app.agents.planner import build_connector
from app.agents.schema_discovery import discover_schema
from app.agents.risk_scan import scan_connection
from app.audit import logger as audit
from app.config import settings

router = APIRouter(prefix="/scan", tags=["scan"])


class ScanRequest(BaseModel):
    connection_id: str


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/stream")
def scan_stream(body: ScanRequest, db: Session = Depends(get_db),
                 ctx: AuthContext = Depends(get_current_user),
                 _billing: AuthContext = Depends(require_active_subscription)):
    user = db.query(User).filter_by(id=ctx.user_id).first()
    row_scope = (user.row_scope or {}) if user else {}
    required = {"querying", "anomaly_detection"}
    if not required.issubset(set(user.capabilities or [])):
        def _denied():
            yield _sse({"type": "step", "step": "policy", "status": "error",
                        "detail": "Your account does not have both querying and "
                                  "anomaly detection enabled, which a risk scan needs."})
        return StreamingResponse(_denied(), media_type="text/event-stream")

    conn_row = db.query(DataSourceConnection).filter_by(
        id=body.connection_id, tenant_id=ctx.tenant_id,
    ).first()
    if not conn_row:
        raise HTTPException(404, "Connection not found or not authorized for this tenant.")

    try:
        check_ask_rate_limit(ctx.user_id)
    except RateLimitExceeded as e:
        audit.log(db, ctx.tenant_id, "scan_rate_limited", ctx.user_id, status="denied",
                   detail={"retry_after_seconds": round(e.retry_after_seconds, 1)})
        raise HTTPException(
            429, f"Too many analyses/scans run recently. Try again in about "
                 f"{e.retry_after_seconds:.0f}s.",
        )

    try:
        acquire_concurrency_slot(ctx.tenant_id)
    except ConcurrencyLimitExceeded as e:
        audit.log(db, ctx.tenant_id, "scan_concurrency_limited", ctx.user_id, status="denied")
        raise HTTPException(429, str(e))

    def gen():
        try:
            yield _sse({"type": "step", "step": "finding_data", "status": "running"})
            connector = build_connector(conn_row)
            tables = discover_schema(connector, conn_row.table_allowlist or None, conn_row.column_policy or {})
            if not tables:
                yield _sse({"type": "step", "step": "finding_data", "status": "error",
                            "detail": "No authorized tables available for this connection."})
                return
            yield _sse({"type": "step", "step": "finding_data", "status": "done",
                        "detail": f"{len(tables)} authorized table(s) available."})

            yield _sse({"type": "step", "step": "scanning", "status": "running",
                        "detail": f"Checking up to {min(len(tables), 10)} table(s) for anomalies."})
            result = scan_connection(
                connector, tables, row_scope,
                row_limit=settings.default_row_limit, timeout_seconds=settings.query_timeout_seconds,
            )
            yield _sse({"type": "step", "step": "scanning", "status": "done",
                        "detail": f"{len(result.scanned_anomalies)} anomal{'y' if len(result.scanned_anomalies) == 1 else 'ies'} "
                                  f"found across {len(result.tables_scanned)} table(s)."})

            for violated_table in result.row_scope_violations:
                audit.log(db, ctx.tenant_id, "row_scope_violation", ctx.user_id, body.connection_id,
                           status="denied", detail={"table": violated_table, "context": "risk_scan"})

            audit.log(db, ctx.tenant_id, "risk_scan_executed", ctx.user_id, body.connection_id,
                       detail={
                           "tables_scanned": len(result.tables_scanned),
                           "tables_skipped": len(result.tables_skipped),
                           "anomalies_found": len(result.scanned_anomalies),
                       })

            yield _sse({
                "type": "result",
                "final": True,
                "tables_scanned": result.tables_scanned,
                "tables_skipped": result.tables_skipped,
                "anomalies": [
                    {"table": sa.table, **asdict(sa.anomaly)} for sa in result.scanned_anomalies
                ],
            })
        except Exception as e:
            yield _sse({"type": "step", "step": "error", "status": "error", "detail": str(e)})
        finally:
            release_concurrency_slot(ctx.tenant_id)

    return StreamingResponse(gen(), media_type="text/event-stream")
