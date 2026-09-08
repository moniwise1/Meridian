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

from sqlalchemy.orm import Session

from app.db.models import Notification, User

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
