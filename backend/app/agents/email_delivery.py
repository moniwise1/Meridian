"""
Email delivery (BUILD SPEC section 23). Email is treated as a
data-exfiltration boundary, not a convenience feature:

  1. verify the requesting user has email_delivery enabled
  2. verify the recipient - sending to the authenticated user's own
     address is auto-approved; any other recipient requires an explicit
     `confirmed=True` from the caller (the frontend gates this behind a
     confirmation dialog)
  3. every attempt is logged, sent, blocked, or failed, with the reason

The actual transport is pluggable (`EmailBackend`), chosen once at import
time by `settings.email_provider`:

  - "console" (default): logs what would have been sent instead of
    sending it. Zero config, what a fresh dev environment gets for free.
  - "smtp": a real, generic SMTP backend (stdlib `smtplib` - no vendor
    SDK), deliberately provider-agnostic rather than committing to one
    specific API. Works with Gmail (an app password), a transactional
    provider's SMTP relay (Postmark/SendGrid/SES all offer one), or a
    domain's own mail hosting - whatever `SMTP_*` settings point at.

Honesty note, same norm this codebase applies to every "no live account
available here" integration (see app/billing/paystack.py,
app/security/secrets.py's AWS KMS backend): SmtpEmailBackend's SMTP
command sequence (EHLO/STARTTLS/LOGIN/MAIL FROM/RCPT TO/DATA, correct
MIME structure with attachment) is verified against a stubbed
`smtplib.SMTP` client - not a real live send, since no SMTP credentials
are available in this environment. Confirm your first real send lands
(and isn't caught by spam filtering) before relying on it for anything
time-sensitive.
"""
import html
import mimetypes
import os
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User, EmailDeliveryLog, Tenant
from app.audit import logger as audit

VALID_OUTBOUND_EMAIL_MODES = ("open", "self_only", "domain_allowlist")


def normalize_outbound_email_policy(raw: dict | None) -> dict:
    """A tenant that predates this feature has NULL here; normalize to the
    'open' default (prior behavior). Also lower-cases the allowlist."""
    raw = raw or {}
    mode = raw.get("mode")
    if mode not in VALID_OUTBOUND_EMAIL_MODES:
        mode = "open"
    domains = [d.strip().lower() for d in (raw.get("allowed_domains") or []) if d and d.strip()]
    return {"mode": mode, "allowed_domains": domains}

# Same brand tokens as frontend/app/globals.css - kept in sync by hand
# since an email needs its styling INLINE (email clients strip <style>
# blocks and ignore CSS variables), not shared CSS the way the web app
# gets it.
_BRAND_TEAL_DEEP = "#123f3d"
_BRAND_TEAL = "#1c5d5a"
_BRAND_PAPER = "#f5f6f4"
_BRAND_INK = "#171a1c"
_BRAND_INK_SOFT = "#565f66"

# Real logo image, served as a static asset off the frontend (frontend/
# public/brand/meridian-logo-email.png) rather than a CSS text badge -
# explicit product decision, even though it means the header renders
# blank in clients that block remote images until "show images" is
# clicked (desktop Outlook, mainly; Gmail/Apple Mail/most mobile clients
# show it immediately). width/height are set explicitly so blocked-image
# state reserves the right amount of space instead of collapsing to
# nothing, and alt text is styled to read reasonably on its own for
# clients that show it.
_BRAND_LOGO_URL = "https://www.getmeridiananalytics.com/brand/meridian-logo-email.png"
_BRAND_LOGO_WIDTH = 170
_BRAND_LOGO_HEIGHT = 41


def _render_html_email(body: str) -> str:
    """Wraps a plain-text email body in a branded HTML shell - a header
    badge (the same wordmark treatment as the web app's own nav) and a
    "Made by Meridian" footer, matching the branding already added to
    every downloaded report/presentation/export. Applies uniformly to
    every email this backend sends (welcome, invites, owner
    notifications, MFA recovery, and the AI agent's "email me this
    report" feature) without any of those callers needing to know or
    care - this is purely a presentation layer over whatever plain-text
    body they already built."""
    escaped = html.escape(body)
    paragraphs = "".join(
        f'<p style="margin:0 0 14px;">{p.replace(chr(10), "<br>")}</p>'
        for p in escaped.split("\n\n") if p.strip()
    )
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px 16px;background:{_BRAND_PAPER};
               font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="100%" style="max-width:520px;" cellpadding="0" cellspacing="0">
          <tr><td align="center" style="padding-bottom:24px;">
            <img src="{_BRAND_LOGO_URL}" alt="Meridian" width="{_BRAND_LOGO_WIDTH}" height="{_BRAND_LOGO_HEIGHT}"
                 style="display:block;border:0;outline:none;text-decoration:none;
                        color:{_BRAND_INK};font-weight:700;font-size:16px;font-family:Georgia,'Times New Roman',serif;">
          </td></tr>
          <tr><td style="background:#ffffff;border:1px solid #e2e4e1;border-radius:6px;
                         padding:28px 32px;color:{_BRAND_INK};font-size:14px;line-height:1.6;">
            {paragraphs}
          </td></tr>
          <tr><td align="center" style="padding:24px 12px;color:{_BRAND_INK_SOFT};
                         font-size:12px;line-height:1.6;">
            Made by Meridian &mdash; Enterprise analytics, read-only by design.<br>
            <a href="https://www.getmeridiananalytics.com" style="color:{_BRAND_TEAL};text-decoration:none;">
              getmeridiananalytics.com
            </a>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""


class EmailBackend(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str, attachment_path: str | None) -> None:
        ...


class ConsoleEmailBackend(EmailBackend):
    """Demo backend: logs what would have been sent instead of sending it.
    Safe default until a real provider is configured."""

    def send(self, to: str, subject: str, body: str, attachment_path: str | None) -> None:
        print(f"[email:console-backend] To: {to} | Subject: {subject} | Attachment: {attachment_path}")


class SmtpEmailBackend(EmailBackend):
    """Generic SMTP over STARTTLS. Raises on any failure (auth, connection,
    refused recipient) rather than swallowing it - the caller (send_report
    below) is what decides how a failed send is recorded and reported,
    this class's only job is "send, or raise a real exception saying why
    not"."""

    def __init__(self, host: str, port: int, username: str, password: str,
                 from_address: str, use_tls: bool):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address or username
        self._use_tls = use_tls

    def send(self, to: str, subject: str, body: str, attachment_path: str | None) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        # A bare address (e.g. "hello@getmeridiananalytics.com") shows up
        # in most inboxes with the local part ("hello") standing in for a
        # sender name, since there isn't one. formataddr produces a
        # correctly quoted/encoded "Meridian <hello@...>" header per RFC
        # 2822, so every client shows the brand name instead of guessing
        # one from the address.
        message["From"] = formataddr(("Meridian", self._from_address))
        message["To"] = to
        # Plain-text part first (the universal fallback every client can
        # render, and what spam filters expect to find alongside HTML),
        # then the branded HTML alternative - this exact order is what
        # produces a correct multipart/alternative structure, per
        # email.message's own documented pattern.
        message.set_content(body)
        message.add_alternative(_render_html_email(body), subtype="html")

        if attachment_path:
            # Guessed from the file extension (reports/exports are always
            # one of PDF/PPTX/CSV/XLSX here) - falls back to a generic
            # binary type rather than failing the whole send over a type
            # the recipient's mail client can still open fine either way.
            ctype, _ = mimetypes.guess_type(attachment_path)
            maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
            with open(attachment_path, "rb") as f:
                message.add_attachment(
                    f.read(), maintype=maintype, subtype=subtype,
                    filename=os.path.basename(attachment_path),
                )

        with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
            smtp.ehlo()
            if self._use_tls:
                smtp.starttls()
                smtp.ehlo()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(message)


def get_backend() -> EmailBackend:
    if settings.email_provider == "smtp":
        return SmtpEmailBackend(
            host=settings.smtp_host, port=settings.smtp_port,
            username=settings.smtp_username, password=settings.smtp_password,
            from_address=settings.smtp_from_address, use_tls=settings.smtp_use_tls,
        )
    return ConsoleEmailBackend()


@dataclass
class DeliveryResult:
    status: str  # "sent" | "blocked" | "pending_confirmation" | "failed"
    reason: str = ""


def send_report(db: Session, tenant_id: str, user_id: str, recipient: str, subject: str,
                 body: str, attachment_path: str | None, artifact_id: str | None,
                 confirmed: bool) -> DeliveryResult:
    user = db.query(User).filter_by(id=user_id, tenant_id=tenant_id).first()
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    recipient_lc = recipient.strip().lower()
    own_lc = (user.email or "").strip().lower() if user else ""
    to_self = recipient_lc == own_lc
    policy = normalize_outbound_email_policy(tenant.outbound_email_policy if tenant else None)
    recipient_domain = recipient_lc.rsplit("@", 1)[-1] if "@" in recipient_lc else ""

    if not user or "email_delivery" not in (user.capabilities or []):
        result = DeliveryResult("blocked", "Email delivery is not enabled for your account.")
    elif not to_self and policy["mode"] == "self_only":
        result = DeliveryResult(
            "blocked",
            "Your organization only allows emailing reports to your own address.",
        )
    elif (not to_self and policy["mode"] == "domain_allowlist"
          and recipient_domain not in policy["allowed_domains"]):
        allowed = ", ".join(policy["allowed_domains"]) or "(no domains configured)"
        result = DeliveryResult(
            "blocked",
            f"Your organization only allows emailing reports to addresses at: {allowed}.",
        )
    elif not to_self and not confirmed:
        result = DeliveryResult(
            "pending_confirmation",
            "Sending to a recipient other than your own address requires confirmation.",
        )
    else:
        try:
            get_backend().send(recipient, subject, body, attachment_path)
            result = DeliveryResult("sent")
        except Exception as e:
            # A real SMTP send has real failure modes (bad credentials, the
            # provider rejecting the recipient, a network timeout) that the
            # console backend never had - this must degrade to a clean,
            # logged "failed" result, not an unhandled exception turning
            # into a 500 for what is, from the caller's point of view, a
            # completely normal "delivery didn't work" outcome.
            result = DeliveryResult("failed", f"Could not send email ({type(e).__name__}).")

    db.add(EmailDeliveryLog(
        tenant_id=tenant_id, user_id=user_id, recipient=recipient, subject=subject,
        artifact_id=artifact_id, status=result.status, reason=result.reason,
    ))
    audit.log(db, tenant_id, "email_delivery_attempt", user_id,
              detail={"recipient": recipient, "status": result.status}, status=result.status)
    db.commit()
    return result
