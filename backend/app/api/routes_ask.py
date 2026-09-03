"""
The core "ask a question" flow (BUILD SPEC sections 12, 17, 18).

Streams progress steps as Server-Sent Events. tenant_id/user_id and the
caller's row-level scope are derived from the verified auth token and the
User row - never from the request body - so a client cannot claim a wider
scope than an admin granted them.
"""
import json
from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.security.auth import get_current_user, require_active_subscription, AuthContext
from app.security.rate_limit import (
    check_ask_rate_limit, acquire_concurrency_slot, release_concurrency_slot,
    RateLimitExceeded, ConcurrencyLimitExceeded,
)
from app.agents.planner import run_analysis, StepEvent, PolicyViolation
from app.audit import logger as audit

router = APIRouter(prefix="/ask", tags=["ask"])


class AskRequest(BaseModel):
    connection_id: str
    question: str
    conversation_id: str | None = None
    document_ids: list[str] = []


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/stream")
def ask_stream(body: AskRequest, db: Session = Depends(get_db),
               ctx: AuthContext = Depends(get_current_user),
               _billing: AuthContext = Depends(require_active_subscription)):
    user = db.query(User).filter_by(id=ctx.user_id).first()
    row_scope = (user.row_scope or {}) if user else {}
    if "querying" not in (user.capabilities or []):
        def _denied():
            yield _sse({"type": "step", "step": "policy", "status": "error",
                        "detail": "Your account does not have querying enabled."})
        return StreamingResponse(_denied(), media_type="text/event-stream")

    if body.document_ids and "document_retrieval" not in (user.capabilities or []):
        def _denied_docs():
            yield _sse({"type": "step", "step": "policy", "status": "error",
                        "detail": "Your account does not have document retrieval enabled."})
        return StreamingResponse(_denied_docs(), media_type="text/event-stream")

    try:
        check_ask_rate_limit(ctx.user_id)
    except RateLimitExceeded as e:
        audit.log(db, ctx.tenant_id, "ask_rate_limited", ctx.user_id, status="denied",
                   detail={"retry_after_seconds": round(e.retry_after_seconds, 1)})
        raise HTTPException(
            429, f"Too many questions asked recently. Try again in about "
                 f"{e.retry_after_seconds:.0f}s.",
        )

    try:
        acquire_concurrency_slot(ctx.tenant_id)
    except ConcurrencyLimitExceeded as e:
        audit.log(db, ctx.tenant_id, "ask_concurrency_limited", ctx.user_id, status="denied")
        raise HTTPException(429, str(e))

    def gen():
        try:
            for event in run_analysis(
                db, ctx.tenant_id, ctx.user_id, body.connection_id,
                body.question, row_scope, body.conversation_id, body.document_ids,
            ):
                if isinstance(event, StepEvent):
                    yield _sse({"type": "step", **asdict(event)})
                else:
                    yield _sse({"type": "result", **event})
        except PolicyViolation as e:
            yield _sse({"type": "step", "step": "policy", "status": "error", "detail": str(e)})
        except Exception as e:
            yield _sse({"type": "step", "step": "error", "status": "error", "detail": str(e)})
        finally:
            # Guaranteed to run if run_analysis raises or completes
            # normally. An early client disconnect also triggers this in
            # practice (Starlette closes the generator), but that path
            # isn't as hard a guarantee as the exception/completion path -
            # worth knowing if slots ever seem to leak under abrupt
            # disconnects.
            release_concurrency_slot(ctx.tenant_id)

    return StreamingResponse(gen(), media_type="text/event-stream")
