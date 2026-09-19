"""
Mirrors each new lead into a Google Sheet.

The sheet is a CONVENIENCE COPY, never the record. `leads` in our own
database is the source of truth (see app/db/models.py Lead), and every code
path here is written so that a sheet which is misconfigured, unreachable,
rate-limited or simply deleted cannot cost a lead or fail a submission:

- the push happens AFTER the lead is committed, in a background task
- a failure is recorded on the row (sheet_sync_error) and retried later,
  rather than raised at the person filling in the form
- retries are bounded, so a permanently wrong URL can't be hammered forever

Delivery is a plain HTTPS POST to a Google Apps Script Web App that the
owner deploys against their own sheet (docs/LEADS_SHEET.md). That was
chosen over the Sheets API deliberately: it needs no service-account key
to be created, downloaded, pasted into a server and then rotated - just one
URL and a shared secret, both of which are ordinary settings. The secret is
checked by the script, so knowing the URL alone isn't enough to write rows.
"""
import logging
from datetime import datetime

import httpx

from app.config import settings
from app.db.models import Lead

log = logging.getLogger(__name__)

# A wrong URL, a sheet that was deleted, a script that no longer exists:
# all permanent. Stop after this many tries and leave the error on the row
# for a human to see, instead of retrying on every page load forever.
MAX_SHEET_ATTEMPTS = 5
_TIMEOUT_SECONDS = 10


def sheet_configured() -> bool:
    return bool(settings.leads_sheet_webhook_url)


def _payload(lead: Lead) -> dict:
    return {
        "secret": settings.leads_sheet_shared_secret,
        "lead": {
            "id": lead.id,
            "received_at": lead.created_at.isoformat() if lead.created_at else "",
            "full_name": lead.full_name,
            "business_name": lead.business_name or "",
            "email": lead.email,
            "phone": lead.phone,
            "message": lead.message or "",
            "source": lead.source or "",
            "campaign": lead.campaign or "",
            "status": lead.status,
        },
    }


def _push(lead: Lead, client: httpx.Client | None = None) -> None:
    """Raises on any failure; callers record it on the row."""
    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        resp = client.post(settings.leads_sheet_webhook_url, json=_payload(lead))
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    finally:
        if owns_client:
            client.close()


def sync_pending(limit: int = 20) -> int:
    """Push every lead that hasn't reached the sheet yet. Opens its own
    short-lived session: this runs as a background task, and a
    request-scoped session must never escape into one. Returns how many
    were delivered."""
    if not sheet_configured():
        return 0
    from app.db.session import SessionLocal

    db = SessionLocal()
    delivered = 0
    try:
        pending = (
            db.query(Lead)
            .filter(Lead.sheet_synced_at.is_(None), Lead.sheet_attempts < MAX_SHEET_ATTEMPTS)
            .order_by(Lead.created_at)
            .limit(limit)
            .all()
        )
        if not pending:
            return 0
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            for lead in pending:
                lead.sheet_attempts = (lead.sheet_attempts or 0) + 1
                try:
                    _push(lead, client=client)
                except Exception as e:  # network, HTTP, bad script - all the same here
                    # Truncated: this is shown in the admin console, and a
                    # Google error page is long enough to be unreadable.
                    lead.sheet_sync_error = str(e)[:300]
                    log.warning("Lead %s could not be written to the sheet: %s", lead.id, e)
                else:
                    lead.sheet_synced_at = datetime.utcnow()
                    lead.sheet_sync_error = None
                    delivered += 1
                db.commit()
        return delivered
    finally:
        db.close()
