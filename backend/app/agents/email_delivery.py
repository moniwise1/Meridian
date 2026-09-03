"""
Email delivery (BUILD SPEC section 23). Email is treated as a
data-exfiltration boundary, not a convenience feature:

  1. verify the requesting user has email_delivery enabled
  2. verify the recipient - sending to the authenticated user's own
     address is auto-approved; any other recipient requires an explicit
     `confirmed=True` from the caller (the frontend gates this behind a
     confirmation dialog)
  3. every attempt is logged, sent or blocked, with the reason

The actual transport is pluggable (`EmailBackend`). This build ships a
`ConsoleEmailBackend` that logs instead of sending - there's no real SMTP
relay or provider credential available in this environment. Swapping in a
real backend (SES, Postmark, SMTP) means implementing `EmailBackend.send`
and pointing `get_backend()` at it; nothing else in the pipeline changes.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from sqlalchemy.orm import Session

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


def get_backend() -> EmailBackend:
    return ConsoleEmailBackend()


@dataclass
class DeliveryResult:
    status: str  # "sent" | "blocked" | "pending_confirmation"
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
        get_backend().send(recipient, subject, body, attachment_path)
        result = DeliveryResult("sent")

    db.add(EmailDeliveryLog(
        tenant_id=tenant_id, user_id=user_id, recipient=recipient, subject=subject,
        artifact_id=artifact_id, status=result.status, reason=result.reason,
    ))
    audit.log(db, tenant_id, "email_delivery_attempt", user_id,
              detail={"recipient": recipient, "status": result.status}, status=result.status)
    db.commit()
    return result
