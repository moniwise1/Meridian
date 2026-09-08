"""
Creating in-app notifications (the dashboard's notification bell - see the
Notification model in app/db/models.py and
frontend/components/NotificationBell.tsx).

Deliberately separate from app/agents/notifications.py, which sends
EMAIL. The platform events worth telling a customer about (subscription
activated, renewing soon, cancelled, a renewal payment failing, a
teammate joining) generally want BOTH: an email so it reaches them when
they're not looking at the app, and an in-app notice so it's still
visible next time they are. The caller does both, side by side; this
module is only the in-app half.

Best-effort by the same norm as the email half: a failed notification
insert is logged and swallowed, never allowed to fail the request that
triggered it (activating a subscription, accepting an invite).
"""
import logging
import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import Notification, Tenant, User

logger = logging.getLogger(__name__)


def tenant_admin_user_ids(db: Session, tenant_id: str) -> list[str]:
    """The recipients for a tenant-level notice - every admin on the
    tenant, mirroring tenant_admin_emails() in app/agents/notifications.py
    so the bell and the owner-activity emails always tell the same people.
    Unlike that function this does NOT exclude anyone: a solo admin who
    just subscribed should still see "your subscription is active" in
    their own bell (the equivalent email is skipped for the actor, but an
    in-app notice they can dismiss is not the same intrusion as an email)."""
    return [u.id for u in db.query(User).filter_by(tenant_id=tenant_id, role="admin").all()]


def create_notification(
    db: Session,
    tenant_id: str,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    user_ids: list[str] | None = None,
) -> None:
    """Insert one Notification row per recipient. user_ids=None means
    "every admin on this tenant". Commits its own rows. Never raises."""
    try:
        recipients = user_ids if user_ids is not None else tenant_admin_user_ids(db, tenant_id)
        for uid in recipients:
            db.add(Notification(
                tenant_id=tenant_id, user_id=uid, kind=kind,
                title=title, body=body, link=link,
            ))
        if recipients:
            db.commit()
    except Exception as e:  # noqa: BLE001 - best-effort, see module docstring
        db.rollback()
        logger.warning("create_notification(%s) failed: %s: %s", kind, type(e).__name__, e)


def maybe_send_expiry_reminder(db: Session, tenant: Tenant | None) -> bool:
    """Send the "your subscription renews in N days" notice + email for ONE
    tenant, but only if it's inside the reminder window and hasn't already
    been reminded for this exact renewal date. Returns True if a reminder
    went out. Never raises.

    Called two ways, both hitting the same once-per-period guard
    (Tenant.expiry_reminder_sent_for):
      - the daily sweep (app/api/routes_notifications.py's reminders/run),
        for a deployment that wired up an external cron;
      - opportunistically whenever the notification bell is polled
        (list_notifications), so a deployment that DIDN'T wire up a cron
        still gets reminders out from normal team activity. The check is a
        couple of cheap comparisons on every poll; it only touches the DB
        the one time per period it actually fires.
    """
    # Imported here rather than at module top to keep this module's import
    # graph flat (app/agents/notifications.py -> email_delivery -> config,
    # all fine, but there's no reason to pull the email stack in for
    # callers that only want create_notification()).
    from app.config import settings
    from app.agents.notifications import send_subscription_expiring
    from app.audit import logger as audit

    try:
        if tenant is None or tenant.subscription_status != "active":
            return False
        expires_at = tenant.subscription_expires_at
        if not expires_at:
            return False

        now = datetime.utcnow()
        cutoff = now + timedelta(days=settings.subscription_expiry_reminder_days)
        if not (now < expires_at <= cutoff):
            return False
        if tenant.expiry_reminder_sent_for == expires_at:
            return False  # already reminded for this exact renewal

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
        for email in (
            u.email for u in db.query(User).filter_by(tenant_id=tenant.id, role="admin")
        ):
            send_subscription_expiring(email, tenant.name, renews_on, days_left)

        tenant.expiry_reminder_sent_for = expires_at
        db.commit()
        audit.log(db, tenant.id, "subscription_expiry_reminder_sent", None,
                  detail={"renews_on": renews_on, "days_left": days_left})
        return True
    except Exception as e:  # noqa: BLE001 - best-effort, see module docstring
        db.rollback()
        logger.warning("maybe_send_expiry_reminder failed: %s: %s", type(e).__name__, e)
        return False
