"""
Transactional / lifecycle system emails - deliberately separate from
send_report in email_delivery.py, which is the AI AGENT's user-directed
"send this report somewhere" feature (capability-gated, confirmation-
gated, because a user pointing the agent at an arbitrary recipient is a
real data-exfiltration risk). Everything here is initiated by the
PLATFORM itself, always to an address already on file (a user's own
registered email, or one an admin/owner just typed in to invite) - never
a recipient an end user supplies to the AI agent - so none of that
gating applies.

Best-effort throughout: a failed system email is logged and swallowed,
never allowed to fail the request that triggered it (registering an
account, signing in, accepting an invite) just because SMTP hiccuped -
see ConsoleEmailBackend/SmtpEmailBackend in email_delivery.py for what
"failed" actually means here (nothing sent at all in console mode, a
real SMTP error in smtp mode).
"""
import logging

from sqlalchemy.orm import Session

from app.agents.email_delivery import get_backend
from app.db.models import User, PlatformStaff

logger = logging.getLogger(__name__)

FOUNDER_NAME = "Joel Umunnah"


def tenant_admin_emails(db: Session, tenant_id: str, exclude_user_id: str | None = None) -> list[str]:
    """The "account owner(s)" for a tenant's owner-activity notifications -
    every admin on it (usually just the one who registered it, but
    notifying all of them if there's more than one is the safer default).
    Excludes exclude_user_id so an admin is never emailed about their own
    action - shared by routes_auth.py and routes_mfa.py, which both issue
    real sign-ins."""
    q = db.query(User).filter_by(tenant_id=tenant_id, role="admin")
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    return [u.email for u in q.all()]


def platform_owner_emails(db: Session, exclude_staff_id: str | None = None) -> list[str]:
    """The platform's own "account owner(s)" - every platform_staff row
    with role="owner" (Meridian's own founder/leadership), excluding
    exclude_staff_id so an owner is never emailed about their own action."""
    q = db.query(PlatformStaff).filter_by(role="owner")
    if exclude_staff_id:
        q = q.filter(PlatformStaff.id != exclude_staff_id)
    return [s.email for s in q.all()]


def _send_best_effort(to: str, subject: str, body: str) -> None:
    try:
        get_backend().send(to, subject, body, attachment_path=None)
    except Exception as e:
        # Never raises - see module docstring. Logged so a real deployment
        # can still notice a pattern of failures (bad SMTP creds, a
        # provider rejecting sends) without it ever surfacing as a 500 to
        # whoever's registering, signing in, or accepting an invite.
        logger.warning("system email to %s (%r) failed: %s: %s", to, subject, type(e).__name__, e)


def send_welcome_email(to_email: str, company_name: str) -> None:
    subject = "Welcome to Meridian"
    body = (
        f"Hi,\n\n"
        f"Welcome to Meridian - I'm {FOUNDER_NAME}, founder.\n\n"
        f"Meridian is your team's AI analytics agent: ask a business question in plain English, "
        f"and it finds the relevant authorized data, analyses it, checks for anomalies, and explains "
        f"the answer with evidence, not just a number. It's read-only by design, so it can query and "
        f"explain, but it can never write, alter, or delete anything in your systems.\n\n"
        f"{company_name}'s workspace is live and ready to go - connect a data source or upload a "
        f"document to get your first real answer.\n\n"
        f"Enjoy the tool, and reply any time if you hit a snag.\n\n"
        f"{FOUNDER_NAME}\n"
        f"Founder, Meridian"
    )
    _send_best_effort(to_email, subject, body)


def send_mfa_recovery_email(to_email: str, recovery_url: str) -> None:
    subject = "Reset two-factor authentication for your Meridian account"
    body = (
        f"Hi,\n\n"
        f"Someone (hopefully you) entered the correct password for your Meridian account but "
        f"couldn't provide a two-factor code, and requested this recovery link.\n\n"
        f"Use it to disable the lost authenticator and set up a new one (expires in 15 minutes):\n"
        f"{recovery_url}\n\n"
        f"If this wasn't you, someone else knows your password - sign in and change it right "
        f"away, and ignore this link.\n\n"
        f"Meridian"
    )
    _send_best_effort(to_email, subject, body)


def send_invite_email(to_email: str, org_label: str, inviter_email: str, role: str, accept_url: str) -> None:
    subject = f"You're invited to join {org_label} on Meridian"
    body = (
        f"Hi,\n\n"
        f"{inviter_email} has invited you to join {org_label} on Meridian as a {role}.\n\n"
        f"Accept your invite here (expires in 24 hours):\n{accept_url}\n\n"
        f"If you don't accept within 24 hours, this invite is automatically revoked and you'll "
        f"need a fresh one.\n\n"
        f"Meridian"
    )
    _send_best_effort(to_email, subject, body)


def notify_owners(recipients: list[str], subject: str, message: str) -> None:
    """Emails every given "account owner" address about a critical
    activity - a sign-in, a teammate/staff invite going out, an invite
    being accepted - so this is visible somewhere other than the in-app
    audit log, which only ever gets checked by someone who thinks to look.
    Best-effort per recipient - one bad address never blocks the others.
    Callers (routes_auth.py, routes_platform.py) compute the recipient
    list themselves (tenant admins / platform owners), typically excluding
    whoever just performed the action so they aren't notified about their
    own activity."""
    for recipient in recipients:
        _send_best_effort(recipient, subject, message)
