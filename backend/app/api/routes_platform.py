"""
Internal admin API for Meridian's own team - the one place in this app
deliberately allowed to see and act across every tenant. Gated by
require_staff_role / get_current_staff from app/security/platform_auth.py,
never by the tenant-scoped auth used everywhere else in the app - see that
module's docstring for why the two are kept structurally separate rather
than one being a role flag on the other.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import (
    Tenant, User, DataSourceConnection, QueryRecord, Conversation,
    GeneratedArtifact, UploadedDocument, EmailDeliveryLog, AuditLog,
    PlatformStaff, SupportTicket, TicketMessage, SystemIncident, IncidentUpdate,
)
from app.security.auth import hash_password, verify_password
from app.security.platform_auth import (
    create_platform_access_token, get_current_staff, require_staff_role, PlatformAuthContext,
)
from app.security.login_cooldown import (
    check_platform_login_cooldown, record_platform_login_failure, record_platform_login_success,
    LoginCooldownActive,
)
from app.audit import logger as audit

router = APIRouter(prefix="/platform", tags=["platform"])


# ---------- Staff auth ----------

class StaffLoginRequest(BaseModel):
    email: EmailStr
    password: str


class StaffTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff_id: str
    role: str


@router.post("/login", response_model=StaffTokenResponse)
def staff_login(body: StaffLoginRequest, db: Session = Depends(get_db)):
    try:
        check_platform_login_cooldown(body.email)
    except LoginCooldownActive as e:
        raise HTTPException(429, str(e))

    staff = db.query(PlatformStaff).filter_by(email=body.email).first()
    if not staff or not verify_password(body.password, staff.password_hash):
        record_platform_login_failure(body.email)
        raise HTTPException(401, "Incorrect email or password.")

    record_platform_login_success(body.email)
    token = create_platform_access_token(staff.id, staff.role)
    return StaffTokenResponse(access_token=token, staff_id=staff.id, role=staff.role)


class StaffBootstrapRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


@router.post("/bootstrap", response_model=StaffTokenResponse)
def bootstrap_owner(body: StaffBootstrapRequest, db: Session = Depends(get_db)):
    """Creates the very first platform-staff account, as an 'owner'. Only
    works when NO staff accounts exist yet - the one and only
    unauthenticated way into this system, and it closes itself after one
    use. Every account after this one is created via POST /platform/staff
    by an existing owner. Run this once right after your first deploy,
    then treat the URL as sensitive until you have — after that it's
    self-disabling regardless."""
    if db.query(PlatformStaff).count() > 0:
        raise HTTPException(403, "A platform staff account already exists; ask an owner to add you instead.")
    staff = PlatformStaff(email=body.email, password_hash=hash_password(body.password), role="owner")
    db.add(staff)
    db.commit()
    db.refresh(staff)
    token = create_platform_access_token(staff.id, staff.role)
    return StaffTokenResponse(access_token=token, staff_id=staff.id, role=staff.role)


class StaffOut(BaseModel):
    id: str
    email: str
    role: str

    class Config:
        from_attributes = True


@router.get("/staff", response_model=list[StaffOut])
def list_staff(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    return db.query(PlatformStaff).all()


class StaffCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "support"


@router.post("/staff", response_model=StaffOut)
def add_staff(body: StaffCreateRequest, db: Session = Depends(get_db),
              ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    if db.query(PlatformStaff).filter_by(email=body.email).first():
        raise HTTPException(400, "An account with this email already exists.")
    staff = PlatformStaff(email=body.email, password_hash=hash_password(body.password), role=body.role)
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


# ---------- Tenants ----------

class TenantUserOut(BaseModel):
    """One sub-account under a tenant, for the platform panel's tenant
    expand view - "when did they open account" is created_at, not
    anything billing-related (a tenant's users all share the tenant's one
    subscription; there's no per-user billing here)."""
    id: str
    email: str
    role: str
    created_at: str


class TenantOut(BaseModel):
    id: str
    name: str
    subscription_status: str
    tier: str
    created_at: str
    subscribed_at: str | None
    subscription_expires_at: str | None
    user_count: int
    connection_count: int
    users: list[TenantUserOut]


def _tenant_out(db: Session, t: Tenant) -> TenantOut:
    users = db.query(User).filter_by(tenant_id=t.id).order_by(User.created_at.asc()).all()
    return TenantOut(
        id=t.id, name=t.name, subscription_status=t.subscription_status, tier=t.tier,
        created_at=t.created_at.isoformat(),
        subscribed_at=t.paid_at.isoformat() if t.paid_at else None,
        subscription_expires_at=t.subscription_expires_at.isoformat() if t.subscription_expires_at else None,
        user_count=len(users),
        connection_count=db.query(DataSourceConnection).filter_by(tenant_id=t.id).count(),
        users=[
            TenantUserOut(id=u.id, email=u.email, role=u.role,
                          created_at=u.created_at.isoformat() if u.created_at else "")
            for u in users
        ],
    )


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    return [_tenant_out(db, t) for t in tenants]


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: str, db: Session = Depends(get_db),
                ctx: PlatformAuthContext = Depends(get_current_staff)):
    t = db.query(Tenant).filter_by(id=tenant_id).first()
    if not t:
        raise HTTPException(404, "Tenant not found.")
    return _tenant_out(db, t)


class TenantUpdate(BaseModel):
    name: str | None = None
    subscription_status: str | None = None


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: str, body: TenantUpdate, db: Session = Depends(get_db),
                   ctx: PlatformAuthContext = Depends(require_staff_role("owner", "support"))):
    t = db.query(Tenant).filter_by(id=tenant_id).first()
    if not t:
        raise HTTPException(404, "Tenant not found.")
    changes = {}
    if body.name is not None:
        changes["name"] = {"from": t.name, "to": body.name}
        t.name = body.name
    if body.subscription_status is not None:
        changes["subscription_status"] = {"from": t.subscription_status, "to": body.subscription_status}
        t.subscription_status = body.subscription_status
        if body.subscription_status == "active":
            # A staff-set "active" is a comp/support override, not a real
            # Paystack charge (see this endpoint's own docstring/the
            # tenants page copy) - it still needs paid_at/expires_at set
            # so the tenant shows up correctly as "on Pro" with real dates
            # rather than active-but-dateless. paid_at only backfills if
            # unset, same anchoring rule _activate() uses for a real
            # payment; expires_at always gets a fresh 30-day window.
            if not t.paid_at:
                t.paid_at = datetime.utcnow()
            t.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
        else:
            # Anything else ("none"/"pending"/"cancelled"/"refunded") is
            # not currently-paying by definition (Tenant.tier), so there's
            # no live expiry to show.
            t.subscription_expires_at = None
    db.commit()
    db.refresh(t)
    audit.log(db, tenant_id, "platform_tenant_updated", detail={"by_staff_id": ctx.staff_id, "changes": changes})
    return _tenant_out(db, t)


@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, db: Session = Depends(get_db),
                   ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    """Irreversibly deletes a tenant and everything scoped to it, including
    its own audit trail (deliberate - this is also how a GDPR-style
    erasure request gets fulfilled, not an oversight). Owner-only: this is
    the single most destructive action in the app. Logged under the
    synthetic tenant_id "platform" since the real one won't exist to query
    against afterward."""
    t = db.query(Tenant).filter_by(id=tenant_id).first()
    if not t:
        raise HTTPException(404, "Tenant not found.")

    # Children before parents, matching this schema's real FK
    # relationships (support_tickets<-ticket_messages); everything else is
    # a plain tenant_id column with no FK, so order among those doesn't
    # matter, but deleting them in one transaction does.
    ticket_ids = [row.id for row in db.query(SupportTicket).filter_by(tenant_id=tenant_id).all()]
    if ticket_ids:
        db.query(TicketMessage).filter(TicketMessage.ticket_id.in_(ticket_ids)).delete(synchronize_session=False)
    db.query(SupportTicket).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(QueryRecord).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(Conversation).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(GeneratedArtifact).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(UploadedDocument).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(EmailDeliveryLog).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(DataSourceConnection).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(User).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.query(AuditLog).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    tenant_name = t.name
    db.delete(t)
    db.commit()

    audit.log(db, "platform", "tenant_deleted",
               detail={"by_staff_id": ctx.staff_id, "tenant_id": tenant_id, "tenant_name": tenant_name})
    return {"status": "deleted"}


# ---------- Support tickets (staff side - cross-tenant) ----------

class TicketMessageOut(BaseModel):
    id: str
    author_type: str
    author_label: str
    body: str
    created_at: str


class TicketOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    subject: str
    status: str
    priority: str
    assigned_to_staff_id: str | None
    created_at: str
    updated_at: str
    messages: list[TicketMessageOut]


def _ticket_out(db: Session, ticket: SupportTicket) -> TicketOut:
    tenant = db.query(Tenant).filter_by(id=ticket.tenant_id).first()
    messages = (
        db.query(TicketMessage).filter_by(ticket_id=ticket.id).order_by(TicketMessage.created_at.asc()).all()
    )
    return TicketOut(
        id=ticket.id, tenant_id=ticket.tenant_id, tenant_name=tenant.name if tenant else "(deleted)",
        subject=ticket.subject, status=ticket.status, priority=ticket.priority,
        assigned_to_staff_id=ticket.assigned_to_staff_id,
        created_at=ticket.created_at.isoformat(), updated_at=ticket.updated_at.isoformat(),
        messages=[
            TicketMessageOut(id=m.id, author_type=m.author_type, author_label=m.author_label,
                              body=m.body, created_at=m.created_at.isoformat())
            for m in messages
        ],
    )


@router.get("/tickets", response_model=list[TicketOut])
def list_all_tickets(status: str | None = None, db: Session = Depends(get_db),
                      ctx: PlatformAuthContext = Depends(get_current_staff)):
    q = db.query(SupportTicket)
    if status:
        q = q.filter_by(status=status)
    tickets = q.order_by(SupportTicket.updated_at.desc()).all()
    return [_ticket_out(db, t) for t in tickets]


class TicketUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    assigned_to_staff_id: str | None = None


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: str, body: TicketUpdate, db: Session = Depends(get_db),
                   ctx: PlatformAuthContext = Depends(get_current_staff)):
    ticket = db.query(SupportTicket).filter_by(id=ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    if body.status is not None:
        ticket.status = body.status
    if body.priority is not None:
        ticket.priority = body.priority
    if body.assigned_to_staff_id is not None:
        ticket.assigned_to_staff_id = body.assigned_to_staff_id
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return _ticket_out(db, ticket)


class TicketReply(BaseModel):
    body: str


@router.post("/tickets/{ticket_id}/messages", response_model=TicketOut)
def staff_reply(ticket_id: str, body: TicketReply, db: Session = Depends(get_db),
                 ctx: PlatformAuthContext = Depends(get_current_staff)):
    ticket = db.query(SupportTicket).filter_by(id=ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    staff = db.query(PlatformStaff).filter_by(id=ctx.staff_id).first()
    db.add(TicketMessage(
        ticket_id=ticket.id, author_type="staff", author_id=ctx.staff_id,
        author_label=staff.email if staff else "staff", body=body.body,
    ))
    ticket.updated_at = datetime.utcnow()
    if ticket.status == "open":
        ticket.status = "in_progress"
    db.commit()
    db.refresh(ticket)
    return _ticket_out(db, ticket)


# ---------- Incidents / internal status management ----------

class IncidentUpdateOut(BaseModel):
    id: str
    status: str
    body: str
    created_at: str


class IncidentOut(BaseModel):
    id: str
    title: str
    status: str
    severity: str
    started_at: str
    resolved_at: str | None
    updates: list[IncidentUpdateOut]


def _incident_out(db: Session, incident: SystemIncident) -> IncidentOut:
    updates = (
        db.query(IncidentUpdate).filter_by(incident_id=incident.id)
        .order_by(IncidentUpdate.created_at.asc()).all()
    )
    return IncidentOut(
        id=incident.id, title=incident.title, status=incident.status, severity=incident.severity,
        started_at=incident.started_at.isoformat(),
        resolved_at=incident.resolved_at.isoformat() if incident.resolved_at else None,
        updates=[IncidentUpdateOut(id=u.id, status=u.status, body=u.body, created_at=u.created_at.isoformat())
                 for u in updates],
    )


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    incidents = db.query(SystemIncident).order_by(SystemIncident.started_at.desc()).limit(50).all()
    return [_incident_out(db, i) for i in incidents]


class IncidentCreate(BaseModel):
    title: str
    severity: str = "minor"
    body: str


@router.post("/incidents", response_model=IncidentOut)
def create_incident(body: IncidentCreate, db: Session = Depends(get_db),
                     ctx: PlatformAuthContext = Depends(get_current_staff)):
    incident = SystemIncident(title=body.title, severity=body.severity, created_by_staff_id=ctx.staff_id)
    db.add(incident)
    db.flush()
    db.add(IncidentUpdate(incident_id=incident.id, status="investigating", body=body.body))
    db.commit()
    db.refresh(incident)
    return _incident_out(db, incident)


class IncidentUpdateCreate(BaseModel):
    status: str
    body: str


@router.post("/incidents/{incident_id}/updates", response_model=IncidentOut)
def add_incident_update(incident_id: str, body: IncidentUpdateCreate, db: Session = Depends(get_db),
                         ctx: PlatformAuthContext = Depends(get_current_staff)):
    incident = db.query(SystemIncident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(404, "Incident not found.")
    incident.status = body.status
    if body.status == "resolved":
        incident.resolved_at = datetime.utcnow()
    db.add(IncidentUpdate(incident_id=incident.id, status=body.status, body=body.body))
    db.commit()
    db.refresh(incident)
    return _incident_out(db, incident)


# ---------- Health snapshot ----------

@router.get("/health-snapshot")
def health_snapshot(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    """A lightweight internal signal, NOT a substitute for real uptime
    monitoring - see the README's note on pairing this with a real
    third-party status/monitoring tool for actual multi-region probing and
    alerting. This just counts recent audit-log entries with status='error'
    as a rough proxy for how much is currently going wrong, plus basic
    tenant/ticket/incident counts."""
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_errors = (
        db.query(AuditLog)
        .filter(AuditLog.status == "error", AuditLog.timestamp >= one_hour_ago)
        .count()
    )
    return {
        "recent_errors_last_hour": recent_errors,
        "active_tenants": db.query(Tenant).filter_by(subscription_status="active").count(),
        "total_tenants": db.query(Tenant).count(),
        "open_tickets": db.query(SupportTicket).filter(SupportTicket.status.in_(["open", "in_progress"])).count(),
        "open_incidents": db.query(SystemIncident).filter(SystemIncident.status != "resolved").count(),
    }
