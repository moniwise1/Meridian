"""
The public "Register your interest" form (frontend/app/interest/page.tsx).

This is the only unauthenticated write endpoint in the app that anyone on
the internet can reach, so it is deliberately narrow: it creates one Lead
row and nothing else. It touches no tenant, grants no access, and returns
nothing about anyone else.

Spam handling, in the order it costs least:
- a honeypot field no human can see or fill; filled in => accepted and
  silently dropped, so the bot gets no signal to adapt
- a per-IP hourly cap, the same mechanism registration already uses
- length limits on every field, enforced by the schema

A second submission from the same email within a day updates that lead and
adds the new message as a comment, rather than creating a duplicate - ad
traffic double-submits constantly, and a sales list full of the same person
three times is worse than useless.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Lead, LeadComment
from app.security.ip_throttle import client_ip, check_lead_form_rate_limit
from app.security.rate_limit import RateLimitExceeded
from app.leads import sheets
from app.audit import logger as audit

router = APIRouter(prefix="/leads", tags=["leads"])

_DUPLICATE_WINDOW = timedelta(days=1)


class LeadIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=32)
    business_name: str | None = Field(default=None, max_length=160)
    message: str | None = Field(default=None, max_length=2000)
    # Straight off the ad link (?source=facebook&campaign=spring), so the
    # admin console can show which campaign produced which enquiry.
    source: str | None = Field(default=None, max_length=60)
    campaign: str | None = Field(default=None, max_length=120)
    consent: bool = False
    # Honeypot. Named like a field a bot expects to find, hidden from
    # people (aria-hidden + off-screen) and never shown in the UI.
    company_website: str | None = Field(default=None, max_length=200)

    @field_validator("phone")
    @classmethod
    def phone_looks_like_a_number(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or any(c.isalpha() for c in cleaned):
            raise ValueError("Enter a phone number we can call you on.")
        if sum(c.isdigit() for c in cleaned) < 7:
            raise ValueError("Enter a phone number we can call you on.")
        return cleaned


@router.post("")
def register_interest(body: LeadIn, request: Request, background_tasks: BackgroundTasks,
                      db: Session = Depends(get_db)):
    # Answered before anything is stored: a bot that fills the hidden field
    # gets the same "thank you" a person does, and learns nothing.
    if body.company_website:
        return {"received": True}

    try:
        check_lead_form_rate_limit(client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many submissions from this network. Please try again later.")

    email = body.email.strip().lower()
    now = datetime.utcnow()
    existing = (
        db.query(Lead)
        .filter(Lead.email == email, Lead.created_at >= now - _DUPLICATE_WINDOW)
        .order_by(Lead.created_at.desc())
        .first()
    )

    if existing:
        existing.full_name = body.full_name.strip()
        existing.phone = body.phone
        existing.business_name = (body.business_name or "").strip() or existing.business_name
        existing.updated_at = now
        if body.message:
            db.add(LeadComment(lead_id=existing.id, kind="note", staff_email=None,
                               body=f"They wrote in again: {body.message.strip()}"))
        # Send the updated details to the sheet again.
        existing.sheet_synced_at = None
        existing.sheet_attempts = 0
        db.commit()
        lead_id = existing.id
    else:
        lead = Lead(
            full_name=body.full_name.strip(),
            business_name=(body.business_name or "").strip() or None,
            email=email,
            phone=body.phone,
            message=(body.message or "").strip() or None,
            source=(body.source or "").strip() or None,
            campaign=(body.campaign or "").strip() or None,
            consented_at=now if body.consent else None,
            status="open",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id

    audit.log(db, "platform", "lead_registered", detail={
        "lead_id": lead_id, "source": body.source or "", "repeat": bool(existing),
    })
    # After the commit, never before: the lead is safe in our own database
    # whatever the sheet does next.
    background_tasks.add_task(sheets.sync_pending)
    return {"received": True}
