"""
The leads CRM in the internal console, plus each staff member's own profile.

Kept out of routes_platform.py on purpose: those routes are the ones a
restricted role must NOT reach (tenants, revenue, the audit trail), while
these two areas are exactly what a salesperson is hired to use. Separate
files make "which of these can sales see?" answerable by looking at the
file, not by reading thirty decorators.

Access is not enforced here at all - app/security/platform_auth.py's
get_current_staff decides, by path prefix, on a default-deny basis.
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Lead, LeadComment, PlatformStaff
from app.security.platform_auth import get_current_staff, PlatformAuthContext
from app.leads import sheets
from app.audit import logger as audit

router = APIRouter(prefix="/platform", tags=["platform-leads"])

VALID_LEAD_STATUSES = ("open", "won", "not_interested", "closed")


# ---------------------------------------------------------------- leads

class LeadCommentOut(BaseModel):
    id: str
    kind: str
    body: str
    staff_email: str | None
    created_at: str


class LeadOut(BaseModel):
    id: str
    full_name: str
    business_name: str | None
    email: str
    phone: str
    message: str | None
    source: str | None
    campaign: str | None
    status: str
    created_at: str
    updated_at: str
    consented: bool
    # So the console can show "this one hasn't reached your sheet yet"
    # rather than leaving it to be discovered in the sheet's absence.
    in_sheet: bool
    sheet_error: str | None
    comments: list[LeadCommentOut]


def _lead_out(db: Session, lead: Lead) -> LeadOut:
    comments = (
        db.query(LeadComment)
        .filter_by(lead_id=lead.id)
        .order_by(LeadComment.created_at.asc())
        .all()
    )
    return LeadOut(
        id=lead.id, full_name=lead.full_name, business_name=lead.business_name,
        email=lead.email, phone=lead.phone, message=lead.message,
        source=lead.source, campaign=lead.campaign, status=lead.status,
        created_at=lead.created_at.isoformat() if lead.created_at else "",
        updated_at=lead.updated_at.isoformat() if lead.updated_at else "",
        consented=lead.consented_at is not None,
        in_sheet=lead.sheet_synced_at is not None,
        sheet_error=lead.sheet_sync_error,
        comments=[
            LeadCommentOut(id=c.id, kind=c.kind, body=c.body, staff_email=c.staff_email,
                           created_at=c.created_at.isoformat() if c.created_at else "")
            for c in comments
        ],
    )


@router.get("/leads", response_model=list[LeadOut])
def list_leads(background_tasks: BackgroundTasks, status: str | None = None, search: str | None = None,
               db: Session = Depends(get_db),
               ctx: PlatformAuthContext = Depends(get_current_staff)):
    q = db.query(Lead)
    if status:
        if status not in VALID_LEAD_STATUSES:
            raise HTTPException(400, f"Status must be one of: {', '.join(VALID_LEAD_STATUSES)}.")
        q = q.filter(Lead.status == status)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Lead.full_name.ilike(like), Lead.business_name.ilike(like),
                         Lead.email.ilike(like), Lead.phone.ilike(like)))
    leads = q.order_by(Lead.created_at.desc()).limit(500).all()
    # Opening the page is also when anything that missed the sheet gets
    # another try - there is no scheduler in this app by design.
    background_tasks.add_task(sheets.sync_pending)
    return [_lead_out(db, lead) for lead in leads]


class LeadStatusUpdate(BaseModel):
    status: str
    # Optional note to record alongside the change ("spoke to him, calling
    # back Friday"), so why it moved is kept with the fact that it moved.
    note: str | None = Field(default=None, max_length=2000)


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead_status(lead_id: str, body: LeadStatusUpdate, db: Session = Depends(get_db),
                       ctx: PlatformAuthContext = Depends(get_current_staff)):
    if body.status not in VALID_LEAD_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(VALID_LEAD_STATUSES)}.")
    lead = db.query(Lead).filter_by(id=lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found.")
    # Closed is final. It is the one status that means "this is finished"
    # - without that, the history becomes a record of somebody clicking
    # back and forth and stops meaning anything. A closed lead who gets in
    # touch again arrives as a NEW lead (see routes_leads.py), so nothing
    # is lost by refusing this.
    if lead.status == "closed" and body.status != "closed":
        raise HTTPException(400, "This lead is closed and can't be reopened. "
                                 "If they get in touch again it will come in as a new lead.")

    staff = db.query(PlatformStaff).filter_by(id=ctx.staff_id).first()
    was = lead.status
    if was != body.status:
        lead.status = body.status
        lead.updated_at = datetime.utcnow()
        db.add(LeadComment(
            lead_id=lead.id, staff_id=ctx.staff_id, staff_email=staff.email if staff else None,
            kind="status", body=f"Status changed from {was.replace('_', ' ')} to {body.status.replace('_', ' ')}.",
        ))
    if body.note and body.note.strip():
        db.add(LeadComment(lead_id=lead.id, staff_id=ctx.staff_id,
                           staff_email=staff.email if staff else None,
                           kind="note", body=body.note.strip()))
    db.commit()
    audit.log(db, "platform", "lead_status_changed", ctx.staff_id,
              detail={"lead_id": lead.id, "from": was, "to": body.status})
    db.refresh(lead)
    return _lead_out(db, lead)


class LeadNoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.post("/leads/{lead_id}/comments", response_model=LeadOut)
def add_lead_comment(lead_id: str, body: LeadNoteIn, db: Session = Depends(get_db),
                     ctx: PlatformAuthContext = Depends(get_current_staff)):
    lead = db.query(Lead).filter_by(id=lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found.")
    staff = db.query(PlatformStaff).filter_by(id=ctx.staff_id).first()
    db.add(LeadComment(lead_id=lead.id, staff_id=ctx.staff_id,
                       staff_email=staff.email if staff else None,
                       kind="note", body=body.body.strip()))
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return _lead_out(db, lead)


# ---------------------------------------------------------------- my profile

class StaffProfileOut(BaseModel):
    id: str
    email: str
    role: str
    full_name: str | None
    phone: str | None
    job_title: str | None
    address: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    # The console nudges anyone whose profile is still blank.
    complete: bool


def _profile_out(staff: PlatformStaff) -> StaffProfileOut:
    return StaffProfileOut(
        id=staff.id, email=staff.email, role=staff.role, full_name=staff.full_name,
        phone=staff.phone, job_title=staff.job_title, address=staff.address,
        emergency_contact_name=staff.emergency_contact_name,
        emergency_contact_phone=staff.emergency_contact_phone,
        complete=bool(staff.full_name and staff.phone and staff.job_title),
    )


@router.get("/me", response_model=StaffProfileOut)
def my_profile(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    staff = db.query(PlatformStaff).filter_by(id=ctx.staff_id).first()
    if not staff:
        raise HTTPException(404, "Staff account not found.")
    return _profile_out(staff)


class StaffProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    job_title: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)


@router.patch("/me/profile", response_model=StaffProfileOut)
def update_my_profile(body: StaffProfileIn, db: Session = Depends(get_db),
                      ctx: PlatformAuthContext = Depends(get_current_staff)):
    """Anyone may edit their OWN details and no one else's: the row is
    looked up from the token's staff id, never from anything the request
    body says."""
    staff = db.query(PlatformStaff).filter_by(id=ctx.staff_id).first()
    if not staff:
        raise HTTPException(404, "Staff account not found.")
    staff.full_name = body.full_name.strip()
    staff.phone = body.phone.strip()
    staff.job_title = body.job_title.strip()
    staff.address = (body.address or "").strip() or None
    staff.emergency_contact_name = (body.emergency_contact_name or "").strip() or None
    staff.emergency_contact_phone = (body.emergency_contact_phone or "").strip() or None
    staff.profile_updated_at = datetime.utcnow()
    db.commit()
    audit.log(db, "platform", "platform_staff_profile_updated", ctx.staff_id)
    return _profile_out(staff)
