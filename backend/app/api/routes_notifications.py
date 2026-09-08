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
    in-process scheduler by design; an external cron MAY call this daily
    for guaranteed timing - see docs/SUBSCRIPTION_REMINDERS.md. It is not
    required: GET /notifications also fires any due reminder
    opportunistically (see maybe_send_expiry_reminder), so normal team
    activity keeps reminders flowing even with no cron wired up. Both
    paths share the same once-per-period guard
    (Tenant.expiry_reminder_sent_for), so they can't double-send.
"""
import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import Notification, Tenant
from app.security.auth import get_current_user, AuthContext
from app.user_notifications import maybe_send_expiry_reminder

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


def _list_for(db: Session, ctx: AuthContext, limit: int = 30) -> NotificationList:
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


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = 30,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    # The bell polls this endpoint while anyone on the team has the app
    # open - so it doubles as the "is a renewal reminder due?" tick that a
    # deployment without an external cron would otherwise never get. Cheap
    # (a couple of date comparisons); only touches the DB the one time per
    # period it actually fires. Best-effort inside the helper - a hiccup
    # here never breaks loading the bell.
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    maybe_send_expiry_reminder(db, tenant)
    return _list_for(db, ctx, limit)


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
    return _list_for(db, ctx)


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
    or the bundled GitHub Action - see docs/SUBSCRIPTION_REMINDERS.md) for
    guaranteed timing. Not required for reminders to work at all -
    GET /notifications fires due reminders opportunistically too - but a
    cron catches a tenant whose team simply hasn't opened the app during
    the window. Idempotent: shares Tenant.expiry_reminder_sent_for with
    that opportunistic path, so a reminder is sent once per renewal period
    no matter which trigger gets there first."""
    tenants = (
        db.query(Tenant)
        .filter(
            Tenant.subscription_status == "active",
            Tenant.subscription_expires_at.isnot(None),
        )
        .all()
    )
    reminded = sum(1 for t in tenants if maybe_send_expiry_reminder(db, t))
    return ReminderRunResult(checked=len(tenants), reminded=reminded)
