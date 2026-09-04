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
import mimetypes
import os
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User, EmailDeliveryLog
from app.audit import logger as audit


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
        message["From"] = self._from_address
        message["To"] = to
        message.set_content(body)

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
    if not user or "email_delivery" not in (user.capabilities or []):
        result = DeliveryResult("blocked", "Email delivery is not enabled for your account.")
    elif recipient.strip().lower() != (user.email or "").strip().lower() and not confirmed:
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
