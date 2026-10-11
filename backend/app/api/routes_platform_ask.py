"""Owner-only Ask over platform operations; never reads customer result snapshots."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Tenant, QueryRecord, SupportTicket
from app.security.platform_auth import require_staff_role, PlatformAuthContext
from app.security.rate_limit import check_ask_rate_limit, RateLimitExceeded
from fastapi import HTTPException

router = APIRouter(prefix="/platform/ask", tags=["platform-ask"])


class PlatformQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    days: int = Field(default=30, ge=1, le=365)


@router.post("")
def ask_platform(body: PlatformQuestion, db: Session = Depends(get_db),
                 ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    try:
        check_ask_rate_limit("platform:" + ctx.staff_id)
    except RateLimitExceeded:
        raise HTTPException(429, "Too many questions. Please try again shortly.")
    now = datetime.utcnow()
    start = now - timedelta(days=body.days)
    q = body.question.lower()
    result = {"generated_at": now.isoformat() + "Z", "period": {"start": start.isoformat() + "Z", "end": now.isoformat() + "Z"},
              "scope": "Meridian platform metadata only; customer data and question content are excluded.",
              "metrics": [], "answer": "Ask about signups, analysis usage, active subscriptions or open support tickets.", "supported": False}
    if any(w in q for w in ("why", "forecast", "predict", "revenue", "profit", "customer data")):
        result["answer"] = "This owner workspace can report platform counts. It cannot establish causes, financial revenue or customer dataset figures."
        return result
    if any(w in q for w in ("signup", "sign-up", "registered", "registration", "new account")):
        value = db.query(Tenant).filter(Tenant.created_at >= start, Tenant.created_at < now).count()
        result.update(answer=f"{value} accounts registered in the last {body.days} days.", supported=True,
                      metrics=[{"label": "New accounts", "value": value, "source": "tenants.created_at", "definition": "Accounts created during the selected UTC window."}])
    elif any(w in q for w in ("question", "usage", "analys", "activity")):
        current = db.query(QueryRecord).filter(QueryRecord.created_at >= start, QueryRecord.created_at < now).count()
        previous = db.query(QueryRecord).filter(QueryRecord.created_at >= start - timedelta(days=body.days), QueryRecord.created_at < start).count()
        result.update(answer=f"{current} saved analyses in the last {body.days} days, compared with {previous} in the preceding equal-length window. This counts successful saved runs, including cache hits; failed attempts are excluded.", supported=True,
                      metrics=[{"label": "Saved analyses", "value": current, "previous": previous, "source": "query_records.created_at", "definition": "Persisted analyses in the UTC window, including cache hits."}])
    elif any(w in q for w in ("subscri", "paying", "active account")):
        total = db.query(Tenant).count()
        active = db.query(Tenant).filter(Tenant.subscription_status == "active").filter(
            (Tenant.subscription_expires_at.is_(None)) | (Tenant.subscription_expires_at > now)).count()
        result.update(answer=f"{active} of {total} registered accounts currently have an active, unexpired subscription status. This includes manual activations and does not establish paid revenue.", supported=True,
                      metrics=[{"label": "Active subscription status", "value": active, "source": "tenants.subscription_status / subscription_expires_at", "definition": "Current status snapshot, including manually activated accounts."}])
    elif any(w in q for w in ("ticket", "support", "backlog")):
        value = db.query(SupportTicket).filter(SupportTicket.status.in_(["open", "in_progress"])).count()
        result.update(answer=f"{value} support tickets are currently open or in progress.", supported=True,
                      metrics=[{"label": "Open support tickets", "value": value, "source": "support_tickets.status", "definition": "Current open/in-progress ticket count, independent of selected period."}])
    return result
