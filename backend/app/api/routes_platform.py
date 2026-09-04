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

from app.config import settings
from app.db.session import get_db
from app.db.models import (
    Tenant, User, DataSourceConnection, QueryRecord, Conversation,
    GeneratedArtifact, UploadedDocument, EmailDeliveryLog, AuditLog,
    PlatformStaff, SupportTicket, TicketMessage, SystemIncident, IncidentUpdate, Invite,
)
from app.security.auth import hash_password, verify_password
from app.security.platform_auth import (
    create_platform_access_token, get_current_staff, require_staff_role, PlatformAuthContext,
)
from app.security.login_cooldown import (
    check_platform_login_cooldown, record_platform_login_failure, record_platform_login_success,
    LoginCooldownActive,
)
import httpx
from app.audit import logger as audit
from app.audit.logger import verify_chain
from app.audit.anchor import publish_checkpoint, fetch_latest_checkpoint, verify_checkpoint, AnchorNotConfigured
from app.billing.plans import PLANS
from app.invites import create_invite, get_invite_by_token, list_invites, revoke_invite, mark_accepted
from app.agents.notifications import send_invite_email, notify_owners, platform_owner_emails

router = APIRouter(prefix="/platform", tags=["platform"])


def _staff_accept_url(token: str) -> str:
    return f"{settings.frontend_origins[0].rstrip('/')}/platform/accept-invite?token={token}"


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
    audit.log(db, "platform", "platform_staff_logged_in", staff.id, detail={"email": staff.email})
    # Owner-activity notification, not just the audit log above - so a
    # platform owner learns about support staff sign-ins (or a co-owner's)
    # somewhere other than the internal admin panel. Excludes the signer
    # themselves, so a solo owner logging in doesn't email themselves.
    notify_owners(
        platform_owner_emails(db, exclude_staff_id=staff.id),
        "Sign-in to the Meridian admin panel",
        f"{staff.email} ({staff.role}) just signed in to the Meridian internal admin panel.",
    )
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
    created_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_staff(cls, s: PlatformStaff) -> "StaffOut":
        return cls(id=s.id, email=s.email, role=s.role,
                    created_at=s.created_at.isoformat() if s.created_at else "")


@router.get("/staff", response_model=list[StaffOut])
def list_staff(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    rows = db.query(PlatformStaff).order_by(PlatformStaff.created_at.asc()).all()
    return [StaffOut.from_staff(s) for s in rows]


VALID_STAFF_ROLES = {"owner", "support"}


# ---------- Staff invites ----------
# Real invite-by-email (app/invites.py), same reasoning and shape as the
# tenant-side team invites in app/api/routes_auth.py - an owner names an
# email + role, the recipient accepts within 24 hours by proving control
# of their inbox and picking their own password, rather than an owner
# choosing a temporary password for them.

class StaffInviteRequest(BaseModel):
    email: EmailStr
    role: str = "support"


class StaffInviteOut(BaseModel):
    id: str
    email: str
    role: str
    status: str
    invited_by_email: str
    created_at: str
    expires_at: str

    @classmethod
    def from_invite(cls, inv: Invite) -> "StaffInviteOut":
        return cls(
            id=inv.id, email=inv.email, role=inv.role, status=inv.status,
            invited_by_email=inv.invited_by_email,
            created_at=inv.created_at.isoformat() if inv.created_at else "",
            expires_at=inv.expires_at.isoformat() if inv.expires_at else "",
        )


@router.post("/staff/invite", response_model=StaffInviteOut)
def invite_staff(body: StaffInviteRequest, db: Session = Depends(get_db),
                  ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    if body.role not in VALID_STAFF_ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(VALID_STAFF_ROLES))}.")
    email = body.email.strip().lower()
    if db.query(PlatformStaff).filter_by(email=email).first():
        raise HTTPException(400, "An account with this email already exists.")

    # Re-inviting the same address replaces any still-pending invite for
    # it, rather than piling up duplicates the owner would have to
    # individually revoke first.
    for existing in list_invites(db, "staff"):
        if existing.status == "pending" and existing.email == email:
            revoke_invite(db, existing)

    inviter = db.query(PlatformStaff).filter_by(id=ctx.staff_id).first()
    invite, token = create_invite(db, "staff", email, body.role, ctx.staff_id, inviter.email)

    send_invite_email(email, "Meridian's internal team", invite.invited_by_email, body.role, _staff_accept_url(token))
    notify_owners(
        platform_owner_emails(db, exclude_staff_id=ctx.staff_id),
        f"{invite.invited_by_email} invited a new staff member",
        f"{invite.invited_by_email} invited {email} to join Meridian's internal team as a {body.role}. "
        f"The invite expires in 24 hours if not accepted.",
    )
    audit.log(db, "platform", "platform_staff_invite_sent", ctx.staff_id, detail={"email": email, "role": body.role})
    return StaffInviteOut.from_invite(invite)


@router.get("/staff/invites", response_model=list[StaffInviteOut])
def list_staff_invites(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    return [StaffInviteOut.from_invite(inv) for inv in list_invites(db, "staff")]


@router.post("/staff/invite/{invite_id}/revoke", response_model=StaffInviteOut)
def revoke_staff_invite(invite_id: str, db: Session = Depends(get_db),
                         ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    invite = db.query(Invite).filter_by(id=invite_id, kind="staff").first()
    if not invite:
        raise HTTPException(404, "Invite not found.")
    if invite.status != "pending":
        raise HTTPException(400, f"This invite is already {invite.status}.")
    revoke_invite(db, invite)
    audit.log(db, "platform", "platform_staff_invite_revoked", ctx.staff_id, detail={"email": invite.email})
    return StaffInviteOut.from_invite(invite)


class StaffInviteLookupOut(BaseModel):
    role: str
    invited_by_email: str
    email: str


@router.get("/staff/invite/lookup", response_model=StaffInviteLookupOut)
def lookup_staff_invite(token: str, db: Session = Depends(get_db)):
    """Public - the accept page needs to show "join as {role}" before the
    visitor has any credentials of their own."""
    invite = get_invite_by_token(db, "staff", token)
    if not invite or invite.status != "pending":
        raise HTTPException(404, "This invite is invalid or has expired.")
    return StaffInviteLookupOut(role=invite.role, invited_by_email=invite.invited_by_email, email=invite.email)


class StaffAcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8)


@router.post("/staff/invite/accept", response_model=StaffTokenResponse)
def accept_staff_invite(body: StaffAcceptInviteRequest, db: Session = Depends(get_db)):
    """Public - same reasoning as /platform/login: the caller has no
    session yet. Creates the real PlatformStaff account only here, at
    acceptance, never at invite time."""
    invite = get_invite_by_token(db, "staff", body.token)
    if not invite or invite.status != "pending":
        raise HTTPException(400, "This invite is invalid or has expired. Ask an owner to send a new one.")
    if db.query(PlatformStaff).filter_by(email=invite.email).first():
        raise HTTPException(400, "An account with this email already exists.")

    staff = PlatformStaff(email=invite.email, password_hash=hash_password(body.password), role=invite.role)
    db.add(staff)
    mark_accepted(db, invite)
    db.commit()
    db.refresh(staff)

    notify_owners(
        platform_owner_emails(db, exclude_staff_id=staff.id),
        f"{staff.email} joined Meridian's internal team",
        f"{staff.email} accepted their invite and joined as a {staff.role}.",
    )
    audit.log(db, "platform", "platform_staff_invite_accepted", staff.id,
               detail={"email": staff.email, "role": staff.role})

    token = create_platform_access_token(staff.id, staff.role)
    return StaffTokenResponse(access_token=token, staff_id=staff.id, role=staff.role)


def _count_owners(db: Session, excluding_id: str | None = None) -> int:
    q = db.query(PlatformStaff).filter_by(role="owner")
    if excluding_id:
        q = q.filter(PlatformStaff.id != excluding_id)
    return q.count()


class StaffUpdate(BaseModel):
    role: str


@router.patch("/staff/{staff_id}", response_model=StaffOut)
def update_staff_role(staff_id: str, body: StaffUpdate, db: Session = Depends(get_db),
                       ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    """Owner-only: promote to full access ("owner") or limit to "support"
    (tenants/tickets/status, no staff management, no tenant deletion - the
    same boundary require_staff_role already draws throughout this file).
    Refuses to demote the last remaining owner - there's no other way back
    into this panel (bootstrap is a one-time, self-disabling endpoint), so
    that would permanently lock every future admin out, not just this one
    account."""
    if body.role not in VALID_STAFF_ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(VALID_STAFF_ROLES))}.")
    staff = db.query(PlatformStaff).filter_by(id=staff_id).first()
    if not staff:
        raise HTTPException(404, "Staff member not found.")

    if staff.role == "owner" and body.role != "owner" and _count_owners(db, excluding_id=staff.id) == 0:
        raise HTTPException(
            400,
            "Can't demote the last owner — there would be no one left who can manage staff "
            "or delete a tenant. Promote another account to owner first.",
        )

    previous_role = staff.role
    staff.role = body.role
    db.commit()
    db.refresh(staff)
    audit.log(db, "platform", "platform_staff_role_changed", ctx.staff_id,
               detail={"target_staff_id": staff.id, "email": staff.email,
                       "from": previous_role, "to": staff.role})
    return StaffOut.from_staff(staff)


@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: str, db: Session = Depends(get_db),
                  ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    """Owner-only, same last-owner protection as demoting one - deleting
    the last owner is exactly as locking as demoting them, so it gets the
    same refusal rather than a second, easier way around it."""
    staff = db.query(PlatformStaff).filter_by(id=staff_id).first()
    if not staff:
        raise HTTPException(404, "Staff member not found.")

    if staff.role == "owner" and _count_owners(db, excluding_id=staff.id) == 0:
        raise HTTPException(
            400,
            "Can't delete the last owner — there would be no one left who can manage staff "
            "or delete a tenant. Promote another account to owner first.",
        )

    deleted_id, deleted_email, deleted_role = staff.id, staff.email, staff.role
    db.delete(staff)
    db.commit()
    audit.log(db, "platform", "platform_staff_deleted", ctx.staff_id,
               detail={"target_staff_id": deleted_id, "email": deleted_email, "role": deleted_role})
    return {"status": "deleted"}


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
    subdomain: str | None
    subscription_status: str
    tier: str
    plan: str | None
    created_at: str
    subscribed_at: str | None
    subscription_expires_at: str | None
    user_count: int
    connection_count: int
    users: list[TenantUserOut]


def _tenant_out(db: Session, t: Tenant) -> TenantOut:
    users = db.query(User).filter_by(tenant_id=t.id).order_by(User.created_at.asc()).all()
    return TenantOut(
        id=t.id, name=t.name, subdomain=t.subdomain,
        subscription_status=t.subscription_status, tier=t.tier, plan=t.plan,
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
    # A real login boundary (see routes_auth.py's login()) - editable here
    # since this is a functional identifier a company might reasonably
    # want changed (a typo in the auto-generated slug, a rename), not
    # just cosmetic. No tenant-admin self-service for this yet, only staff.
    subdomain: str | None = None
    subscription_status: str | None = None
    # Which plan to comp them onto when setting subscription_status to
    # "active" by hand (see app/billing/plans.py) - optional; defaults to
    # "premium" (see below) rather than leaving it unset, since an unset
    # plan on an "active" tenant would otherwise fall back to the FREE
    # tier's 1-seat cap (seat_limit_for(None) == 1) despite being marked
    # active - the opposite of what a comp override is for.
    plan: str | None = None


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: str, body: TenantUpdate, db: Session = Depends(get_db),
                   ctx: PlatformAuthContext = Depends(require_staff_role("owner", "support"))):
    t = db.query(Tenant).filter_by(id=tenant_id).first()
    if not t:
        raise HTTPException(404, "Tenant not found.")
    if body.plan is not None and body.plan not in PLANS and body.plan != "":
        raise HTTPException(400, f"Unknown plan '{body.plan}'. Choose one of: {', '.join(PLANS)}, or '' to clear it.")

    changes = {}
    if body.name is not None:
        changes["name"] = {"from": t.name, "to": body.name}
        t.name = body.name
    if body.subdomain is not None:
        import re
        from app.tenant_slug import RESERVED_SUBDOMAINS
        candidate = body.subdomain.strip().lower()
        if not re.fullmatch(r"[a-z0-9-]{1,63}", candidate):
            raise HTTPException(400, "Subdomain can only contain lowercase letters, numbers, and hyphens.")
        if candidate in RESERVED_SUBDOMAINS:
            raise HTTPException(400, f"'{candidate}' is reserved and can't be used as a subdomain.")
        clash = db.query(Tenant).filter(Tenant.subdomain == candidate, Tenant.id != tenant_id).first()
        if clash:
            raise HTTPException(400, f"'{candidate}' is already in use by another tenant.")
        changes["subdomain"] = {"from": t.subdomain, "to": candidate}
        t.subdomain = candidate
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
            t.plan = body.plan if body.plan else (t.plan or "premium")
        else:
            # Anything else ("none"/"pending"/"cancelled"/"refunded") is
            # not currently-paying by definition (Tenant.tier), so there's
            # no live expiry or plan to show.
            t.subscription_expires_at = None
            t.plan = None
    elif body.plan is not None:
        # Changing just the plan on an already-active tenant (e.g.
        # comping them up from Basic to Premium) without touching status.
        changes["plan"] = {"from": t.plan, "to": body.plan or None}
        t.plan = body.plan or None
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


# ---------- Platform activity (staff logins + everything staff have done) ----------
#
# Every consequential action any platform staff member takes is already
# audit-logged under the synthetic tenant_id "platform" (staff add/role
# change/delete, tenant edits/deletion, ticket replies, incident updates,
# and now - as of this endpoint's addition - staff logins). This just
# exposes that trail, mirroring app/api/routes_audit.py's tenant-facing
# shape exactly (same fields, same /verify companion) so staff can see who
# on the team did what and when, the same way a tenant's own admin can for
# their org. Open to any authenticated staff member, not owner-only -
# same choice the tenant-facing /audit makes: visibility into what
# happened isn't as sensitive as the ability to change something, so it
# isn't gated the same way staff/tenant management is.

@router.get("/audit")
def list_platform_audit(limit: int = 200, db: Session = Depends(get_db),
                         ctx: PlatformAuthContext = Depends(get_current_staff)):
    rows = (
        db.query(AuditLog)
        .filter_by(tenant_id="platform")
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id, "timestamp": r.timestamp.isoformat(), "action": r.action,
            "status": r.status, "detail": r.detail, "entry_hash": r.entry_hash,
        }
        for r in rows
    ]


@router.get("/audit/verify")
def verify_platform_audit(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    return verify_chain(db, "platform")


# ---------- Externally-anchored checkpoints (app/audit/anchor.py) ----------
# Owner-only to PUBLISH (a real write to an external system, using a real
# credential - same gating tier as staff/tenant management, not the
# read-only audit views above). Any staff role can VERIFY, matching this
# section's own "seeing isn't as sensitive as changing" convention.

@router.post("/audit/checkpoint")
def publish_audit_checkpoint(db: Session = Depends(get_db),
                              ctx: PlatformAuthContext = Depends(require_staff_role("owner"))):
    try:
        result = publish_checkpoint(db)
    except AnchorNotConfigured as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"GitHub rejected the checkpoint write ({e.response.status_code}).")
    audit.log(db, "platform", "audit_checkpoint_published", ctx.staff_id,
              detail={"root_hash": result["checkpoint"]["root_hash"], "commit_url": result["commit_url"]})
    return result


@router.get("/audit/checkpoint/latest")
def get_latest_audit_checkpoint(db: Session = Depends(get_db), ctx: PlatformAuthContext = Depends(get_current_staff)):
    try:
        checkpoint = fetch_latest_checkpoint()
    except AnchorNotConfigured as e:
        raise HTTPException(400, str(e))
    if not checkpoint:
        raise HTTPException(404, "No checkpoint has been published yet.")
    return verify_checkpoint(db, checkpoint)


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
