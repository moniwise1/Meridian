"""Private recurring analyses. Current permissions and plan allowances apply to every run."""
import hmac
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.config import settings
from app.db.session import get_db, SessionLocal
from app.db.models import AnalysisSchedule, User, Tenant, Notification
from app.security.auth import get_current_user, require_active_subscription, AuthContext
from app.security.rate_limit import acquire_concurrency_slot, release_concurrency_slot, ConcurrencyLimitExceeded
from app.api.routes_analyst import authorize_source
from app.api.routes_artifacts import create_report
from app.agents.planner import run_analysis, StepEvent, ClarificationEvent
from app.billing.plans import query_limit_for
from app.billing.usage import count_queries_this_month

router = APIRouter(prefix="/schedules", tags=["schedules"])
log = logging.getLogger(__name__)


class ScheduleInput(BaseModel):
    source_key: str = Field(max_length=150)
    document_ids: list[str] = Field(default_factory=list, max_length=9)
    question: str = Field(min_length=1, max_length=8000)
    frequency: Literal["daily", "weekly"] = "weekly"
    first_run_at: datetime
    generate_pdf: bool = True
    alert_metric: str | None = Field(default=None, max_length=150)
    alert_above: Literal["above", "below"] | None = None
    alert_threshold: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_alert(self):
        parts = (self.alert_metric, self.alert_above, self.alert_threshold)
        if any(p is not None for p in parts):
            if not all(p is not None and p != "" for p in parts):
                raise ValueError("Supply the exact metric label, comparison and threshold together.")
            try:
                value = Decimal(self.alert_threshold)
                if not value.is_finite() or abs(value) > Decimal("1e15"):
                    raise ValueError("Choose a finite threshold within the supported range.")
            except InvalidOperation:
                raise ValueError("Threshold must be a decimal number.")
        if self.first_run_at.tzinfo is None:
            raise ValueError("First run must include a timezone.")
        return self


def summary(row):
    return {"id": row.id, "source_key": row.source_key, "question": row.question,
        "frequency": row.frequency, "next_run_at": row.next_run_at.isoformat() + "Z",
        "enabled": row.enabled, "status": row.status, "last_message": row.last_message,
        "last_query_id": row.last_query_id, "generate_pdf": row.generate_pdf,
        "alert_metric": row.alert_metric, "alert_above": row.alert_above, "alert_threshold": row.alert_threshold}


@router.get("")
def list_schedules(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return [summary(row) for row in db.query(AnalysisSchedule).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id).order_by(AnalysisSchedule.created_at.desc()).all()]


@router.post("")
def create_schedule(body: ScheduleInput, db: Session = Depends(get_db),
                    ctx: AuthContext = Depends(get_current_user), _paid=Depends(require_active_subscription)):
    source, user = authorize_source(db, ctx, body.source_key)
    for doc_id in body.document_ids:
        authorize_source(db, ctx, "doc:" + doc_id)
    if body.generate_pdf and "report_generation" not in (user.capabilities or []):
        raise HTTPException(403, "Report generation is required to schedule PDFs.")
    first = body.first_run_at.astimezone(timezone.utc).replace(tzinfo=None)
    if first <= datetime.utcnow() or first > datetime.utcnow() + timedelta(days=366):
        raise HTTPException(422, "Choose a first run in the next 366 days.")
    if db.query(AnalysisSchedule).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id).count() >= 20:
        raise HTTPException(422, "Pause or remove an existing schedule before adding more (20 per person).")
    values = body.model_dump(exclude={"first_run_at"})
    row = AnalysisSchedule(tenant_id=ctx.tenant_id, user_id=ctx.user_id, next_run_at=first, **values)
    db.add(row); db.commit(); db.refresh(row)
    return summary(row)


class ScheduleUpdate(BaseModel):
    enabled: bool


@router.patch("/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    row = db.query(AnalysisSchedule).filter_by(id=schedule_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id).first()
    if not row: raise HTTPException(404, "Schedule not found.")
    row.enabled = body.enabled
    db.commit()
    return summary(row)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    row = db.query(AnalysisSchedule).filter_by(id=schedule_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id).first()
    if not row: raise HTTPException(404, "Schedule not found.")
    if row.status == "running": raise HTTPException(409, "Wait for this run to finish before removing its schedule.")
    db.delete(row); db.commit()
    return {"deleted": True}


def run_one(db, row, now):
    """Advance before external work. Missed intervals never cause a burst of paid runs."""
    if row.next_run_at > now: return False
    step = timedelta(days=1 if row.frequency == "daily" else 7)
    next_run = row.next_run_at
    while next_run <= now:
        next_run += step
    claimed = db.query(AnalysisSchedule).filter(AnalysisSchedule.id == row.id,
        AnalysisSchedule.enabled == True, AnalysisSchedule.next_run_at == row.next_run_at,
        or_(AnalysisSchedule.status != "running", AnalysisSchedule.last_run_at < now - timedelta(minutes=30))).update(
            {"status": "running", "last_run_at": now, "next_run_at": next_run}, synchronize_session=False)
    db.commit()
    if not claimed: return False
    db.refresh(row)
    slot = False
    try:
        user = db.query(User).filter_by(id=row.user_id, tenant_id=row.tenant_id).first()
        if not user: raise HTTPException(403, "Schedule owner is unavailable.")
        ctx = AuthContext(user.id, user.tenant_id, user.role)
        require_active_subscription(ctx, db)
        authorize_source(db, ctx, row.source_key)
        for doc_id in row.document_ids or []: authorize_source(db, ctx, "doc:" + doc_id)
        tenant = db.query(Tenant).filter_by(id=row.tenant_id).first()
        limit = query_limit_for(tenant.plan)
        if limit is not None and count_queries_this_month(db, row.tenant_id) >= limit:
            raise HTTPException(402, "Monthly question allowance reached.")
        acquire_concurrency_slot(row.tenant_id); slot = True
        kind, _, source_id = row.source_key.partition(":")
        docs = list(dict.fromkeys(([source_id] if kind == "doc" else []) + (row.document_ids or [])))
        result = None
        for event in run_analysis(db, row.tenant_id, row.user_id, source_id if kind == "conn" else None,
                row.question, user.row_scope or {}, document_ids=docs, force_answer=False):
            if isinstance(event, ClarificationEvent):
                raise HTTPException(422, "This question needs clarification. Ask it manually before scheduling it.")
            if isinstance(event, StepEvent) and event.status == "error":
                raise HTTPException(422, "The scheduled analysis could not finish under current source permissions.")
            if isinstance(event, dict) and event.get("final"): result = event
        if not result: raise HTTPException(422, "No completed analysis was produced.")
        row.last_query_id = result["query_id"]
        message = "Your scheduled analysis is ready."
        if row.generate_pdf:
            try:
                create_report(result["query_id"], db, ctx)
                message += " Its PDF is available in your Library."
            except HTTPException:
                message += " A PDF could not be generated under your current report permissions or allowance."
        if row.alert_metric:
            metrics = (result.get("analysis") or {}).get("metrics", [])
            metric = next((m for m in metrics if m.get("label") == row.alert_metric), None)
            value = metric.get("value") if metric else None
            if value is None:
                message += " Alert was not evaluated: the exact computed metric was unavailable."
                row.last_alert_state = False
            else:
                number, threshold = Decimal(str(value)), Decimal(row.alert_threshold)
                crossed = number > threshold if row.alert_above == "above" else number < threshold
                if crossed and not row.last_alert_state:
                    db.add(Notification(tenant_id=row.tenant_id, user_id=row.user_id, kind="analysis_alert",
                        title="Scheduled analysis threshold crossed", body=f"{row.alert_metric}: {number} ({row.alert_above} {threshold}).",
                        link=f"/analyses/{result['query_id']}"))
                row.last_alert_state = crossed
        db.add(Notification(tenant_id=row.tenant_id, user_id=row.user_id, kind="scheduled_analysis",
            title="Scheduled analysis ready", body=message, link=f"/analyses/{result['query_id']}"))
        row.status, row.last_message = "complete", message
    except (HTTPException, ConcurrencyLimitExceeded) as exc:
        db.rollback()
        row.status, row.last_message = "blocked", str(exc.detail) if isinstance(exc, HTTPException) else "Another analysis is running. Try again on the next scheduled interval."
    except Exception:
        db.rollback()
        log.exception("Scheduled analysis failed: %s", row.id)
        row.status, row.last_message = "failed", "Analysis could not finish. Check your source and try the question manually."
    finally:
        if slot: release_concurrency_slot(row.tenant_id)
        db.commit()
    return True


def run_due(tenant_id=None, user_id=None):
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        query = db.query(AnalysisSchedule).filter(AnalysisSchedule.enabled == True, AnalysisSchedule.next_run_at <= now)
        if tenant_id is not None: query = query.filter_by(tenant_id=tenant_id, user_id=user_id)
        rows = query.order_by(AnalysisSchedule.next_run_at).limit(10).all()
        return sum(run_one(db, row, now) for row in rows)
    finally: db.close()


def verify_runner(x_schedule_secret: str | None = Header(default=None)):
    if not settings.analysis_schedule_secret: raise HTTPException(503, "Scheduled runner is not configured.")
    if not x_schedule_secret or not hmac.compare_digest(x_schedule_secret, settings.analysis_schedule_secret):
        raise HTTPException(401, "Invalid schedule runner secret.")


@router.post("/run-due", dependencies=[Depends(verify_runner)])
def run_all_due(): return {"started": run_due()}


@router.post("/check-due")
def check_due(background_tasks: BackgroundTasks, ctx: AuthContext = Depends(get_current_user)):
    background_tasks.add_task(run_due, ctx.tenant_id, ctx.user_id)
    return {"queued": True}
