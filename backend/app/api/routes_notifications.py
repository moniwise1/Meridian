"""
In-app notifications - the dashboard's notification bell
(frontend/components/NotificationBell.tsx).

Two audiences, two auth models:

  - GET /notifications, POST /notifications/read: an ordinary signed-in
    user reading / clearing their own notices. Tenant-scoped the same way
    every other tenant route is (get_current_user), and additionally
    scoped to the caller's own user_id - notifications are per-user
    (see the Notification model docstring).

  - POST /notifications/reminders/run: the "subscription renews in N days"
    sweep. Cross-tenant by nature (it walks every active subscription),
    so it is NOT a human route - it's authenticated by a shared secret
    (SUBSCRIPTION_REMINDER_SECRET), the same "machine, not human" auth as
    /monitor/heartbeat and the Paystack webhook. This app has no
    in-process scheduler by design; an external cron calls this daily -
    see docs/SUBSCRIPTION_REMINDERS.md. Idempotent: each tenant is
    reminded once per billing period, tracked by
    Tenant.expiry_reminder_sent_for, not once per day for the whole window.
"""
import hmac
import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import Notification, Tenant, User
from app.security.auth import get_current_user, AuthContext
from app.agents.notifications import send_subscription_expiring
from app.user_notifications import create_notification, tenant_admin_user_ids
from app.audit import logger as audit

router = APIRouter(prefix="/notifications", tags=["notifications"])

_LIST_CEILING = 100


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    link: str | None
    created_at: str
    read: bool


class NotificationList(BaseModel):
    notifications: list[NotificationOut]
    unread_count: int


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = 30,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    rows = (
        db.query(Notification)
        .filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        .order_by(Notification.created_at.desc())
        .limit(min(max(limit, 1), _LIST_CEILING))
        .all()
    )
    # unread_count is over ALL of this user's notifications, not just the
    # page returned - the bell's badge must stay honest past the 30 shown.
    unread_count = (
        db.query(Notification)
        .filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, read_at=None)
        .count()
    )
    return NotificationList(
        notifications=[
            NotificationOut(
                id=r.id, kind=r.kind, title=r.title, body=r.body, link=r.link,
                created_at=r.created_at.isoformat(), read=r.read_at is not None,
            )
            for r in rows
        ],
        unread_count=unread_count,
    )


class MarkReadRequest(BaseModel):
    # Specific ids to mark read, or all=True for "mark everything read".
    # Exactly one is expected; all=True wins if both are sent.
    ids: list[str] | None = None
    all: bool = False


@router.post("/read", response_model=NotificationList)
def mark_read(
    body: MarkReadRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    q = db.query(Notification).filter_by(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, read_at=None
    )
    if not body.all:
        # Filter to the requested ids. An id that isn't this user's own
        # simply doesn't match - no error, no cross-user write.
        q = q.filter(Notification.id.in_(body.ids or []))
    now = datetime.utcnow()
    for row in q.all():
        row.read_at = now
    db.commit()
    return list_notifications(limit=30, db=db, ctx=ctx)


# --------------------------------------------------------------------------
# Subscription-expiry reminder sweep (external cron -> this endpoint)
# --------------------------------------------------------------------------

def _verify_reminder_secret(x_reminder_secret: str | None = Header(default=None)) -> None:
    if not settings.subscription_reminder_secret:
        raise HTTPException(503, "Subscription reminders are not configured on this deployment.")
    if not x_reminder_secret or not hmac.compare_digest(
        x_reminder_secret, settings.subscription_reminder_secret
    ):
        raise HTTPException(401, "Invalid reminder secret.")


class ReminderRunResult(BaseModel):
    checked: int   # active subscriptions with a known renewal date (all of them)
    reminded: int  # how many got a fresh reminder this run


@router.post(
    "/reminders/run",
    response_model=ReminderRunResult,
    dependencies=[Depends(_verify_reminder_secret)],
)
def run_expiry_reminders(db: Session = Depends(get_db)) -> ReminderRunResult:
    """Called on a daily schedule by an external cron (a Railway Cron Job
    or a scheduled GitHub Action - see docs/SUBSCRIPTION_REMINDERS.md).
    Sends the "your subscription renews in N days" notice - in-app and by
    email - to every tenant whose active subscription expires within the
    reminder window and that hasn't already been reminded for this exact
    expiry date. Safe to run more than once a day: a second run the same
    day is a near-total no-op (every match already has
    expiry_reminder_sent_for set to the current expiry)."""
    window_days = settings.subscription_expiry_reminder_days
    now = datetime.utcnow()
    cutoff = now + timedelta(days=window_days)

    # Every active subscription with a known renewal date - `checked` in
    # the result is this whole count (a stable "how many I'm tracking"
    # number for the cron's own logs), the reminder itself only fires
    # inside the window.
    tenants = (
        db.query(Tenant)
        .filter(
            Tenant.subscription_status == "active",
            Tenant.subscription_expires_at.isnot(None),
        )
        .all()
    )

    reminded = 0
    for tenant in tenants:
        expires_at = tenant.subscription_expires_at
        if not (now < expires_at <= cutoff):
            continue  # not inside the reminder window (yet, or already past)
        if tenant.expiry_reminder_sent_for == expires_at:
            continue  # already reminded for this exact period

        # Whole days, rounded UP - an expiry 4 days and 20 hours out is
        # "5 days", not "4" (a plain .days attribute truncates).
        days_left = max(1, math.ceil((expires_at - now).total_seconds() / 86400))
        renews_on = expires_at.strftime("%d %B %Y")

        create_notification(
            db, tenant.id, "subscription_expiring",
            title=f"Subscription renews in {days_left} day{'s' if days_left != 1 else ''}",
            body=(
                f"Your Meridian subscription is due to renew on {renews_on}. "
                f"No action needed unless you want to change or cancel the plan."
            ),
            link="/billing",
        )
        for email in (u.email for u in db.query(User).filter_by(tenant_id=tenant.id, role="admin")):
            send_subscription_expiring(email, tenant.name, renews_on, days_left)

        tenant.expiry_reminder_sent_for = expires_at
        db.commit()
        audit.log(db, tenant.id, "subscription_expiry_reminder_sent", None,
                  detail={"renews_on": renews_on, "days_left": days_left})
        reminded += 1

    return ReminderRunResult(checked=len(tenants), reminded=reminded)
