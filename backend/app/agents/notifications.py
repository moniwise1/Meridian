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
from app.config import settings
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
        f"Meridian is your team's AI analytics agent: just ask a business question, "
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


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    subject = "Reset your Meridian password"
    body = (
        f"Hi,\n\n"
        f"An admin on your team requested a password reset for your Meridian account.\n\n"
        f"Use this link to sign in and set a new password (expires in 30 minutes):\n"
        f"{reset_url}\n\n"
        f"If you didn't expect this, you can ignore it - your password stays unchanged until "
        f"the link above is actually used.\n\n"
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


def send_subscription_confirmation(
    to_email: str, company_name: str, plan_label: str, amount_naira: str, renews_on: str,
    refund_days: int | None = None,
) -> None:
    """`amount_naira` already carries its own period ("NGN 7,500/month",
    "NGN 85,500/year" - see plans.price_label), so this must not append one:
    it used to add " / month", which after annual billing shipped read
    "NGN 85,500/year / month". `refund_days` is the window for THIS
    subscription's interval; it falls back to the monthly window for any
    caller that doesn't pass it."""
    subject = "Your Meridian subscription is active"
    days = refund_days if refund_days is not None else settings.billing_refund_window_days
    body = (
        f"Hi,\n\n"
        f"{company_name}'s Meridian subscription is now active.\n\n"
        f"Plan: {plan_label}\n"
        f"Amount: {amount_naira}\n"
        f"Renews on: {renews_on}\n\n"
        f"You can review or cancel your plan any time from Billing in the app. "
        f"A cancellation within the first {days} "
        f"days is a full self-serve refund.\n\n"
        f"Thanks for choosing Meridian.\n\n"
        f"{FOUNDER_NAME}\n"
        f"Founder, Meridian"
    )
    _send_best_effort(to_email, subject, body)


def send_subscription_expiring(
    to_email: str, company_name: str, renews_on: str, days_left: int
) -> None:
    day_word = "day" if days_left == 1 else "days"
    subject = f"Your Meridian subscription renews in {days_left} {day_word}"
    body = (
        f"Hi,\n\n"
        f"A heads-up: {company_name}'s Meridian subscription is due to renew on "
        f"{renews_on} ({days_left} {day_word} from now).\n\n"
        f"You don't need to do anything - the renewal is automatic as long as your "
        f"card on file is valid. If you want to change or cancel the plan, or update "
        f"the payment method, do it from Billing in the app before the renewal date.\n\n"
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


def lead_email_fields(lead) -> dict:
    """Copies the handful of fields the enquiry email needs out of a Lead
    row, while its database session is still open.

    send_new_lead_email runs as a background task, after the request's
    session has been closed. Handing it the ORM object instead of this
    plain dict means every attribute it reads is a lazy load against a
    dead session, which raises DetachedInstanceError - the lead is saved,
    but the email that was the whole point never goes out.
    """
    return {
        "full_name": lead.full_name,
        "business_name": lead.business_name,
        "phone": lead.phone,
        "email": lead.email,
        "message": lead.message,
        "source": lead.source,
        "campaign": lead.campaign,
        "consented": lead.consented_at is not None,
    }


def send_new_lead_email(lead: dict, *, repeat: bool = False) -> None:
    """Emails the enquiries inbox when someone fills in the "Inquire now"
    form, on the website or from an ad. Takes the dict from
    lead_email_fields, never a Lead row.

    Sent for every real enquiry and for a same-day follow-up from someone
    already in the list, because a person who writes in twice is the one
    most worth calling back. Honeypot submissions never reach here - they
    are dropped in routes_leads.py before a Lead is created.

    Nothing here may raise. Capturing the lead is the job that matters;
    telling someone about it is not allowed to endanger it, so the whole
    body is guarded rather than just the send. A lead sitting unnoticed
    in the console is a bad day. A lead lost because a mail server was
    misconfigured is a lost customer.

    Nothing about the enquirer is sent anywhere except this one address,
    which is the Company's own inbox.
    """
    try:
        to = (settings.leads_notification_email or "").strip()
        if not to:
            return

        business = (lead.get("business_name") or "").strip()
        name = lead.get("full_name") or "Someone"
        who = f"{name} ({business})" if business else name
        subject = f"Enquiry follow-up: {who}" if repeat else f"New enquiry: {who}"

        origin = settings.frontend_origins[0] if settings.frontend_origins else ""
        came_from = " / ".join(
            p for p in ((lead.get("source") or "").strip(), (lead.get("campaign") or "").strip()) if p
        )

        lines = [
            "Someone wrote in again through the Inquire now form."
            if repeat else
            "A new enquiry came in through the Inquire now form.",
            "",
            f"Name: {name}",
        ]
        if business:
            lines.append(f"Business: {business}")
        lines += [f"Phone: {lead.get('phone') or ''}", f"Email: {lead.get('email') or ''}"]
        if came_from:
            lines.append(f"Came from: {came_from}")
        if not lead.get("consented"):
            lines.append("Note: they did not tick the box agreeing to be contacted.")
        if (lead.get("message") or "").strip():
            lines += ["", "What they said:", lead["message"].strip()]
        if origin:
            lines += ["", f"Open it in the console: {origin}/platform/leads"]
        lines += ["", "Meridian"]

        _send_best_effort(to, subject, "\n".join(lines))
    except Exception as e:
        logger.warning("lead notification email failed: %s: %s", type(e).__name__, e)
