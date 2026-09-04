"""
Registration and login (BUILD SPEC section 6 - human control starts with
knowing who the human is). `register` creates a new tenant + its first
admin user in one step; everyone after that is invited via `invite` by an
admin and sets their password via `login`-style flow... kept intentionally
minimal here: `add_user` lets an existing admin create teammates directly
with a temporary password, since there's no email-sending identity yet to
build a real invite-link flow on top of (see the email module for why).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Tenant, User
from app.security.auth import (
    hash_password, verify_password, create_access_token, create_pre_auth_token,
    decode_pre_auth_token, get_current_user, require_role, AuthContext,
)
from app.security.login_cooldown import (
    check_tenant_login_cooldown, record_tenant_login_failure, record_tenant_login_success,
    LoginCooldownActive,
)
from app.billing.plans import seat_limit_for, get_plan
from app.tenant_slug import generate_unique_subdomain
from app.audit import logger as audit

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    company_name: str
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # The subdomain the caller is currently on (wamco.getmeridiananalytics.com
    # -> "wamco"), sent by the frontend - see lib/subdomain.ts. Omitted
    # entirely (None) when signing in from the generic domain, which stays
    # unrestricted - any valid user, any tenant, exactly as before this
    # feature existed. Provided, it's a real boundary: the account must
    # belong to the tenant that subdomain resolves to, or login is
    # refused even with a correct password - see login() below.
    subdomain: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    user_id: str
    role: str
    subdomain: str | None = None
    # Only populated by /auth/handoff/redeem below - register()/login()
    # leave this unset since the frontend already has the email from
    # whatever form the caller just typed it into.
    email: str | None = None


class LoginResponse(BaseModel):
    """Login is a two-step handshake once MFA is involved (see
    app/api/routes_mfa.py's module docstring for why an access_token can't
    just be handed out immediately once a tenant/user requires a code).
    Exactly one of two shapes comes back:
    - mfa_required=False: access_token is set, exactly like the old
      TokenResponse-only login - the common case, unchanged for every
      tenant that hasn't turned MFA on.
    - mfa_required=True: access_token is null; pre_auth_token is set
      instead, redeemable at POST /auth/mfa/verify-login (mfa_setup_
      required=False - the user already has a code-producing app set up)
      or POST /auth/mfa/setup-login + /confirm-login (mfa_setup_
      required=True - first time this user has hit the org's policy)."""
    mfa_required: bool = False
    mfa_setup_required: bool = False
    pre_auth_token: str | None = None
    access_token: str | None = None
    token_type: str = "bearer"
    tenant_id: str
    user_id: str
    role: str
    subdomain: str | None = None


class AddUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "analyst"


class TenantBySubdomain(BaseModel):
    name: str
    subdomain: str


@router.get("/tenant-by-subdomain/{subdomain}", response_model=TenantBySubdomain)
def get_tenant_by_subdomain(subdomain: str, db: Session = Depends(get_db)):
    """Public, unauthenticated - lets the login page show "Sign in to
    WAMCO" before anyone's identified themselves. Deliberately returns
    only the company's own display name - nothing here is sensitive, the
    same reasoning already applied to making GET /billing/plans public."""
    tenant = db.query(Tenant).filter_by(subdomain=subdomain).first()
    if not tenant:
        raise HTTPException(404, "No workspace found at this address.")
    return TenantBySubdomain(name=tenant.name, subdomain=tenant.subdomain)


# ---------- Cross-subdomain session handoff ----------
# Logging in on the generic domain (www/bare) and landing on
# wamco.getmeridiananalytics.com afterward means handing a session across
# to a genuinely different browser origin - sessionStorage is per-origin
# by design (that isolation is exactly what makes one tenant's subdomain
# unable to read another's session), so this can't be a plain redirect.
#
# Deliberately NOT "put the real access_token in the URL and let the
# other side read it" (the old OAuth "implicit flow" pattern, now
# considered unsafe precisely because a long-lived credential sitting in
# a URL can linger in browser history/referrers/logs). Instead, a short-
# lived (5 min, same TTL as the login-time MFA pre-auth tokens - reuses
# the exact same create_pre_auth_token/decode_pre_auth_token machinery,
# purpose="handoff") single-purpose token goes in the URL FRAGMENT
# specifically (never sent to any server, browser-only) - even if it
# lingers somewhere, it can only ever be redeemed for a session belonging
# to the user who already had one, never a privilege escalation, and only
# within its short window.
#
# Not single-use-tracked (no server-side revocation list for it) - the
# short TTL is doing that job instead, same trade-off the MFA pre-auth
# tokens already make. A production system with Redis available could
# tighten this to one-time-use; not implemented here.

class HandoffTokenOut(BaseModel):
    handoff_token: str


@router.post("/handoff/create", response_model=HandoffTokenOut)
def create_handoff(ctx: AuthContext = Depends(get_current_user)):
    """Called by the frontend, authenticated with whatever access_token it
    JUST obtained (from register/login/MFA), right before navigating to
    the tenant's own subdomain - minted at the moment of redirect, not
    earlier, so its 5-minute window is never eaten by however long MFA
    setup/entry took first."""
    return HandoffTokenOut(handoff_token=create_pre_auth_token(ctx.user_id, ctx.tenant_id, purpose="handoff"))


@router.post("/handoff/redeem", response_model=TokenResponse)
def redeem_handoff(body: HandoffTokenOut, db: Session = Depends(get_db)):
    """Public - the whole point is the caller has NO session yet on this
    origin. Issues a genuinely fresh access_token rather than reusing
    anything from the original login, so the handoff token itself never
    needs to carry the real session material."""
    claims = decode_pre_auth_token(body.handoff_token, expected_purpose="handoff")
    user = db.query(User).filter_by(id=claims["sub"], tenant_id=claims["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "This link has expired. Please sign in again.")
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    token = create_access_token(user.id, user.tenant_id, user.role)
    return TokenResponse(
        access_token=token, tenant_id=user.tenant_id, user_id=user.id, role=user.role,
        subdomain=tenant.subdomain if tenant else None, email=user.email,
    )


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(400, "An account with this email already exists.")

    tenant = Tenant(name=body.company_name)
    # Assigned once, here, and never silently regenerated - this is a real
    # login boundary from this point on (see login() below), so a
    # mid-life change would need a deliberate platform-staff edit
    # (PATCH /platform/tenants/{id}), not happen as a side effect of
    # something else.
    tenant.subdomain = generate_unique_subdomain(db, body.company_name)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = User(
        tenant_id=tenant.id, email=body.email, role="admin",
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, tenant.id, user.role)
    return TokenResponse(
        access_token=token, tenant_id=tenant.id, user_id=user.id, role=user.role,
        subdomain=tenant.subdomain,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    try:
        check_tenant_login_cooldown(body.email)
    except LoginCooldownActive as e:
        raise HTTPException(429, str(e))

    user = db.query(User).filter_by(email=body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        record_tenant_login_failure(body.email)
        raise HTTPException(401, "Incorrect email or password.")

    # Password is correct — this clears the password-guessing cooldown
    # regardless of what happens with MFA below, since that guard exists
    # specifically to blunt password guessing, a fully separate concern
    # from the code check (see app/security/login_cooldown.py's mfa guard).
    record_tenant_login_success(body.email)

    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()

    # Subdomain boundary (wamco.getmeridiananalytics.com only lets WAMCO's
    # own users in). Only enforced when the caller actually sent one - the
    # generic domain's login stays fully unrestricted, unchanged from
    # before this feature existed. Deliberately checked AFTER password
    # verification (a wrong password still gets the ordinary "incorrect
    # email or password", unaffected by this) and with ONE generic message
    # regardless of whether the subdomain doesn't exist at all or just
    # doesn't match this user's tenant - either way tells an attacker
    # nothing more than "not this account, not here."
    if body.subdomain and (not tenant or tenant.subdomain != body.subdomain):
        raise HTTPException(403, "This account isn't part of this organization's workspace.")

    mfa_required = bool(user.totp_enabled) or bool(tenant and tenant.require_mfa)
    if not mfa_required:
        audit.log(db, user.tenant_id, "user_logged_in", user.id)
        token = create_access_token(user.id, user.tenant_id, user.role)
        return LoginResponse(
            access_token=token, tenant_id=user.tenant_id, user_id=user.id, role=user.role,
            subdomain=tenant.subdomain if tenant else None,
        )

    # MFA needed. Withhold a real session until a second endpoint
    # (app/api/routes_mfa.py) redeems this pre-auth token with a code -
    # see that module's docstring for why this can't just issue the
    # access_token now and check the code as an afterthought.
    if user.totp_enabled:
        pre_auth_token = create_pre_auth_token(user.id, user.tenant_id, purpose="mfa_verify")
        return LoginResponse(
            mfa_required=True, mfa_setup_required=False, pre_auth_token=pre_auth_token,
            tenant_id=user.tenant_id, user_id=user.id, role=user.role,
            subdomain=tenant.subdomain if tenant else None,
        )
    # Tenant policy requires MFA but this user hasn't enrolled yet (e.g.
    # added before the policy existed, or before their first login since
    # it changed) - route them through setup instead of a code prompt.
    pre_auth_token = create_pre_auth_token(user.id, user.tenant_id, purpose="mfa_setup")
    return LoginResponse(
        mfa_required=True, mfa_setup_required=True, pre_auth_token=pre_auth_token,
        tenant_id=user.tenant_id, user_id=user.id, role=user.role,
        subdomain=tenant.subdomain if tenant else None,
    )


@router.post("/users", response_model=TokenResponse)
def add_user(body: AddUserRequest, db: Session = Depends(get_db),
             ctx: AuthContext = Depends(get_current_user)):
    if ctx.role != "admin":
        raise HTTPException(403, "Only an admin can add teammates.")
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(400, "An account with this email already exists.")

    # Seat cap: each plan (see app/billing/plans.py) allows a different
    # number of accounts - free is 1 (the admin who registered), Basic 3,
    # Pro 10, Premium unlimited. 402, matching
    # require_active_subscription's convention elsewhere
    # (app/security/auth.py) - this is a plan limit, not a permissions
    # error, and the caller IS allowed to act, just not on this plan.
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")
    seat_limit = seat_limit_for(tenant.plan if tenant.tier == "pro" else None)
    if seat_limit is not None:
        existing_count = db.query(User).filter_by(tenant_id=ctx.tenant_id).count()
        if existing_count >= seat_limit:
            if tenant.tier == "free":
                raise HTTPException(
                    402,
                    "The free plan is limited to 1 account. Subscribe on the Billing page to add teammates.",
                )
            plan = get_plan(tenant.plan) if tenant.plan else None
            plan_label = plan.label if plan else "current"
            raise HTTPException(
                402,
                f"The {plan_label} plan is limited to {seat_limit} accounts. "
                f"Upgrade on the Billing page to add more teammates.",
            )

    user = User(
        tenant_id=ctx.tenant_id, email=body.email, role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.tenant_id, user.role)
    return TokenResponse(access_token=token, tenant_id=user.tenant_id, user_id=user.id, role=user.role)


@router.get("/me")
def me(ctx: AuthContext = Depends(get_current_user)):
    return {"user_id": ctx.user_id, "tenant_id": ctx.tenant_id, "role": ctx.role}


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    row_scope: dict
    created_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_user(cls, u: User) -> "UserOut":
        return cls(id=u.id, email=u.email, role=u.role, row_scope=u.row_scope,
                    created_at=u.created_at.isoformat() if u.created_at else "")


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("admin"))):
    users = db.query(User).filter_by(tenant_id=ctx.tenant_id).order_by(User.created_at.asc()).all()
    return [UserOut.from_user(u) for u in users]


VALID_TENANT_ROLES = {"admin", "manager", "executive", "analyst", "viewer"}


def _count_admins(db: Session, tenant_id: str, excluding_id: str | None = None) -> int:
    q = db.query(User).filter_by(tenant_id=tenant_id, role="admin")
    if excluding_id:
        q = q.filter(User.id != excluding_id)
    return q.count()


class UserRoleUpdate(BaseModel):
    role: str


@router.patch("/users/{user_id}/role", response_model=UserOut)
def update_user_role(user_id: str, body: UserRoleUpdate, db: Session = Depends(get_db),
                      ctx: AuthContext = Depends(require_role("admin"))):
    """Admin-only: give full access ("admin") or limit responsibility to
    one of the other roles. Refuses to demote the last remaining admin -
    admin is required for team management, billing, and connecting data
    sources (see require_role("admin") throughout this app), so zero
    admins would lock the whole organization out of managing itself with
    no way back in short of a platform-staff support override."""
    if body.role not in VALID_TENANT_ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(VALID_TENANT_ROLES))}.")
    user = db.query(User).filter_by(id=user_id, tenant_id=ctx.tenant_id).first()
    if not user:
        raise HTTPException(404, "User not found.")

    if user.role == "admin" and body.role != "admin" and _count_admins(db, ctx.tenant_id, excluding_id=user.id) == 0:
        raise HTTPException(
            400,
            "Can't change the last admin's role — there would be no one left who can manage "
            "the team, billing, or data sources. Promote another teammate to admin first.",
        )

    previous_role = user.role
    user.role = body.role
    db.commit()
    db.refresh(user)
    audit.log(db, ctx.tenant_id, "user_role_changed", ctx.user_id,
               detail={"target_user_id": user_id, "from": previous_role, "to": user.role})
    return UserOut.from_user(user)


@router.delete("/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db),
                 ctx: AuthContext = Depends(require_role("admin"))):
    """Admin-only, same last-admin protection as changing one's role -
    removing the last admin is exactly as locking as demoting them."""
    user = db.query(User).filter_by(id=user_id, tenant_id=ctx.tenant_id).first()
    if not user:
        raise HTTPException(404, "User not found.")

    if user.role == "admin" and _count_admins(db, ctx.tenant_id, excluding_id=user.id) == 0:
        raise HTTPException(
            400,
            "Can't remove the last admin — there would be no one left who can manage the "
            "team, billing, or data sources. Promote another teammate to admin first.",
        )

    deleted_id, deleted_email = user.id, user.email
    db.delete(user)
    db.commit()
    audit.log(db, ctx.tenant_id, "user_removed", ctx.user_id,
               detail={"target_user_id": deleted_id, "email": deleted_email})
    return {"status": "deleted"}


class RowScopeUpdate(BaseModel):
    # e.g. {"region": ["South-East"]}. Empty dict = unrestricted.
    row_scope: dict[str, list[str]]


@router.patch("/users/{user_id}/row_scope", response_model=UserOut)
def update_row_scope(user_id: str, body: RowScopeUpdate, db: Session = Depends(get_db),
                      ctx: AuthContext = Depends(require_role("admin"))):
    user = db.query(User).filter_by(id=user_id, tenant_id=ctx.tenant_id).first()
    if not user:
        raise HTTPException(404, "User not found.")
    user.row_scope = body.row_scope
    db.commit()
    db.refresh(user)
    audit.log(db, ctx.tenant_id, "user_row_scope_updated", ctx.user_id,
               detail={"target_user_id": user_id, "row_scope": body.row_scope})
    return UserOut.from_user(user)
