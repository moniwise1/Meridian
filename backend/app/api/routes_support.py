"""
Customer-facing support tickets - tenant-scoped (any authenticated user in
an org can file/view/reply to their own org's tickets, using the same
get_current_user as every other tenant route), unlike
routes_platform.py's staff-side view across every tenant's tickets.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import SupportTicket, TicketMessage, User
from app.security.auth import get_current_user, AuthContext

router = APIRouter(prefix="/support", tags=["support"])


class TicketMessageOut(BaseModel):
    id: str
    author_type: str
    author_label: str
    body: str
    created_at: str


class TicketOut(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    created_at: str
    updated_at: str
    messages: list[TicketMessageOut]


def _ticket_out(db: Session, ticket: SupportTicket) -> TicketOut:
    messages = (
        db.query(TicketMessage).filter_by(ticket_id=ticket.id).order_by(TicketMessage.created_at.asc()).all()
    )
    return TicketOut(
        id=ticket.id, subject=ticket.subject, status=ticket.status, priority=ticket.priority,
        created_at=ticket.created_at.isoformat(), updated_at=ticket.updated_at.isoformat(),
        messages=[
            TicketMessageOut(id=m.id, author_type=m.author_type, author_label=m.author_label,
                              body=m.body, created_at=m.created_at.isoformat())
            for m in messages
        ],
    )


@router.get("/tickets", response_model=list[TicketOut])
def list_my_tickets(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    tickets = (
        db.query(SupportTicket).filter_by(tenant_id=ctx.tenant_id)
        .order_by(SupportTicket.updated_at.desc()).all()
    )
    return [_ticket_out(db, t) for t in tickets]


class TicketCreate(BaseModel):
    subject: str
    body: str
    priority: str = "normal"


@router.post("/tickets", response_model=TicketOut)
def create_ticket(body: TicketCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    user = db.query(User).filter_by(id=ctx.user_id).first()
    ticket = SupportTicket(
        tenant_id=ctx.tenant_id, created_by_user_id=ctx.user_id,
        subject=body.subject, priority=body.priority,
    )
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(
        ticket_id=ticket.id, author_type="customer", author_id=ctx.user_id,
        author_label=user.email if user else "customer", body=body.body,
    ))
    db.commit()
    db.refresh(ticket)
    return _ticket_out(db, ticket)


class TicketReply(BaseModel):
    body: str


@router.post("/tickets/{ticket_id}/messages", response_model=TicketOut)
def reply_to_ticket(ticket_id: str, body: TicketReply, db: Session = Depends(get_db),
                     ctx: AuthContext = Depends(get_current_user)):
    ticket = db.query(SupportTicket).filter_by(id=ticket_id, tenant_id=ctx.tenant_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    user = db.query(User).filter_by(id=ctx.user_id).first()
    db.add(TicketMessage(
        ticket_id=ticket.id, author_type="customer", author_id=ctx.user_id,
        author_label=user.email if user else "customer", body=body.body,
    ))
    if ticket.status in ("resolved", "closed"):
        ticket.status = "open"  # replying to a resolved ticket reopens it
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return _ticket_out(db, ticket)
