"""
TOTP-based multi-factor authentication (RFC 6238 - "Google Authenticator"-
style: a QR code enrolls a secret into the user's authenticator app, which
then produces a new 6-digit code every 30 seconds).

Two entirely separate flows share the same TOTP primitives at the bottom
of this file:

1. **Self-service**, for a user who already has a real session (enabling/
   confirming/disabling their own MFA, e.g. from the Security page, or the
   mandatory setup step shown right after registration - see
   `app/api/routes_auth.py`'s `register()`, unchanged, and
   `frontend/app/login/page.tsx`). Ordinary `get_current_user` bearer auth.

2. **Login-time**, for the moment BEFORE a real session exists - the
   password was correct but a code (or, for a tenant that has since turned
   on the org-wide policy, first-time enrollment) still stands between
   here and a usable session. This is the entire reason MFA is worth
   building at all: if `POST /auth/login` just handed back a real
   access_token immediately and only checked the code afterward, a
   correct password alone would already be sufficient to reach every
   other authenticated endpoint, defeating the point. Instead it hands
   back a short-lived "pre-auth" token (`app/security/auth.py`) that is
   explicitly rejected by `get_current_user` and can only ever be redeemed
   here, at `/verify-login` or `/setup-login` + `/confirm-login`. Login-
   time code guessing is rate-limited the same way password guessing
   already is (`app/security/login_cooldown.py`'s dedicated mfa guard) -
   a 6-digit code is a much smaller space than a password.

3. **Email recovery**, for a user who's lost their authenticator device
   entirely (no code to enter, no self-service way back in otherwise).
   Reachable only from the mfa_verify step of #2 above - i.e. only after
   a correct password, never a bare "enter your email" form, so it can't
   be used to enumerate accounts or spam an arbitrary address. Emails a
   longer-lived (15 min, not the shared 5) recovery link to the account's
   OWN registered address; following it disables the lost authenticator
   (`totp_enabled=False`), so the next login re-enrolls a fresh one -
   exactly what an admin does by hand removing and re-adding a locked-out
   teammate today, just self-service. A security-REDUCING action, so the
   frontend requires an explicit confirm click on the recovery page
   rather than firing automatically on load (an automated link-scanner
   prefetching the URL must not silently disable someone's MFA). The
   tenant's other admin(s) are emailed about it immediately either way -
   see app/agents/notifications.py - since if it wasn't the real user,
   that's exactly the kind of event an owner needs to see right away.

NOT built: backup/recovery CODES (a printed list of one-time-use backup
codes) as an alternative to the email-recovery path above - a real
product might offer both; only the email path is built here. If the
account's own email is itself compromised, both a password reset (not
built - see the honesty note in app/agents/email_delivery.py, same
"no live SMTP identity to test a real reset flow against until now"
gap that's since closed enough to build this) and this MFA-recovery
path share that limitation; the platform-staff support path remains the
final backstop for a fully locked-out admin.
"""
import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import Tenant, User
from app.security.auth import (
    AuthContext, create_access_token, create_pre_auth_token, decode_pre_auth_token, get_current_user,
)
from app.security.login_cooldown import (
    LoginCooldownActive, check_mfa_login_cooldown, record_mfa_login_failure, record_mfa_login_success,
)
from app.security.secrets import decrypt, encrypt
from app.audit import logger as audit
from app.agents.notifications import notify_owners, tenant_admin_emails, send_mfa_recovery_email

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

ISSUER = "Meridian"

# Longer than the shared 5-minute PRE_AUTH_TTL_SECONDS (see
# create_pre_auth_token's ttl_seconds override) - realistically checking
# an inbox and clicking a link takes longer than the few seconds the
# other pre-auth purposes are sized for.
RECOVERY_TTL_SECONDS = 15 * 60


def _recovery_url(tenant: Tenant | None, token: str) -> str:
    if tenant and tenant.subdomain:
        return f"https://{tenant.subdomain}.{settings.apex_domain}/mfa-recovery?token={token}"
    return f"{settings.frontend_origins[0].rstrip('/')}/mfa-recovery?token={token}"


def _mask_email(email: str) -> str:
    """For display only ("we sent a link to j***9@gmail.com") - never used
    for anything security-relevant, the real recovery email always goes to
    the account's own address regardless of what this shows."""
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[0] + "*" * max(len(local) - 1, 1)
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}" if domain else masked


def _qr_data_uri(otpauth_uri: str) -> str:
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _new_secret_response(email: str, secret: str) -> dict:
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)
    # `secret` is also returned in plain text (Base32, the standard
    # manual-entry format every authenticator app accepts) alongside the QR
    # code - a phone camera that can't scan the screen still needs a way in.
    # This is the ONE moment this value is ever sent to the frontend at
    # all; from here on only its encrypted form is stored, and no endpoint
    # anywhere returns it again.
    return {"secret": secret, "qr_code": _qr_data_uri(uri)}


def _verify_code(encrypted_secret: str, code: str) -> bool:
    try:
        secret = decrypt(encrypted_secret)
    except Exception:
        return False
    return pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1)


class ConfirmRequest(BaseModel):
    code: str


class DisableRequest(BaseModel):
    code: str


class PolicyRequest(BaseModel):
    require_mfa: bool


class LoginCodeRequest(BaseModel):
    pre_auth_token: str
    code: str


class PreAuthTokenOnly(BaseModel):
    pre_auth_token: str


# ---------- self-service (already has a real session) ----------

@router.get("/status")
def mfa_status(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    user = db.query(User).filter_by(id=ctx.user_id).first()
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    return {"enabled": bool(user.totp_enabled), "tenant_requires_mfa": bool(tenant.require_mfa)}


@router.post("/setup")
def setup(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    """Starts (or restarts) enrollment. Generates a fresh secret and holds
    it un-confirmed (totp_enabled stays False) until /confirm proves the
    user actually scanned it - calling this again before confirming just
    replaces the pending secret, so an abandoned/failed attempt is never
    stuck."""
    user = db.query(User).filter_by(id=ctx.user_id).first()
    secret = pyotp.random_base32()
    user.totp_secret = encrypt(secret)
    user.totp_enabled = False
    db.commit()
    return _new_secret_response(user.email, secret)


@router.post("/confirm")
def confirm(body: ConfirmRequest, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    user = db.query(User).filter_by(id=ctx.user_id).first()
    if not user.totp_secret:
        raise HTTPException(400, "Start setup first.")
    if not _verify_code(user.totp_secret, body.code):
        raise HTTPException(400, "Incorrect code. Check your authenticator app and try again.")
    user.totp_enabled = True
    audit.log(db, ctx.tenant_id, "mfa_enabled", ctx.user_id)
    db.commit()
    return {"enabled": True}


@router.post("/disable")
def disable(body: DisableRequest, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    if tenant.require_mfa:
        raise HTTPException(403, "Your organization requires two-factor authentication — it can't be disabled.")
    user = db.query(User).filter_by(id=ctx.user_id).first()
    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(400, "Two-factor authentication is not enabled.")
    # Requires a currently-valid code, not just a click - the same reason
    # /connections requires the DB password again to change a live
    # connection, this is a security-reducing action and shouldn't be one
    # accidental click (or one XSS'd request) away with nothing else needed.
    if not _verify_code(user.totp_secret, body.code):
        raise HTTPException(400, "Incorrect code.")
    user.totp_enabled = False
    user.totp_secret = None
    audit.log(db, ctx.tenant_id, "mfa_disabled", ctx.user_id)
    db.commit()
    return {"enabled": False}


@router.patch("/policy")
def set_policy(body: PolicyRequest, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    """Org-wide policy toggle - admin only. Turning this on does NOT
    retroactively enroll anyone; each user (including one who was already
    logged in when this changed) hits the mfa_setup_required path the next
    time they log in - see /auth/login in routes_auth.py."""
    if ctx.role != "admin":
        raise HTTPException(403, "Only an admin can change this.")
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    tenant.require_mfa = body.require_mfa
    audit.log(db, ctx.tenant_id, "mfa_policy_changed", ctx.user_id, detail={"require_mfa": body.require_mfa})
    db.commit()
    return {"require_mfa": tenant.require_mfa}


# ---------- login-time (no real session yet - see module docstring) ----------

@router.post("/verify-login")
def verify_login(body: LoginCodeRequest, db: Session = Depends(get_db)):
    """Redeems a pre-auth token issued by POST /auth/login for an already-
    enrolled user (mfa_setup_required=False there) into a real session,
    once the code checks out."""
    claims = decode_pre_auth_token(body.pre_auth_token, expected_purpose="mfa_verify")
    user = db.query(User).filter_by(id=claims["sub"], tenant_id=claims["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "Invalid login attempt.")

    try:
        check_mfa_login_cooldown(user.id)
    except LoginCooldownActive as e:
        raise HTTPException(429, str(e))

    if not user.totp_enabled or not user.totp_secret or not _verify_code(user.totp_secret, body.code):
        record_mfa_login_failure(user.id)
        raise HTTPException(401, "Incorrect code.")

    record_mfa_login_success(user.id)
    audit.log(db, user.tenant_id, "user_logged_in", user.id, detail={"mfa": True})
    notify_owners(
        tenant_admin_emails(db, user.tenant_id, exclude_user_id=user.id),
        "Sign-in to your Meridian workspace",
        f"{user.email} ({user.role}) just signed in to your Meridian workspace.",
    )
    token = create_access_token(user.id, user.tenant_id, user.role)
    return {
        "access_token": token, "token_type": "bearer",
        "tenant_id": user.tenant_id, "user_id": user.id, "role": user.role,
    }


@router.post("/setup-login")
def setup_login(body: PreAuthTokenOnly, db: Session = Depends(get_db)):
    """The login-time equivalent of /setup, for a user whose tenant now
    requires MFA but who hasn't enrolled yet (mfa_setup_required=True from
    POST /auth/login) - they have no real session to call /setup with, so
    this redeems the pre-auth token instead. Does NOT issue a real session
    by itself; the user still has to prove the code back at /confirm-login."""
    claims = decode_pre_auth_token(body.pre_auth_token, expected_purpose="mfa_setup")
    user = db.query(User).filter_by(id=claims["sub"], tenant_id=claims["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "Invalid login attempt.")
    secret = pyotp.random_base32()
    user.totp_secret = encrypt(secret)
    user.totp_enabled = False
    db.commit()
    return _new_secret_response(user.email, secret)


@router.post("/confirm-login")
def confirm_login(body: LoginCodeRequest, db: Session = Depends(get_db)):
    claims = decode_pre_auth_token(body.pre_auth_token, expected_purpose="mfa_setup")
    user = db.query(User).filter_by(id=claims["sub"], tenant_id=claims["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "Invalid login attempt.")

    try:
        check_mfa_login_cooldown(user.id)
    except LoginCooldownActive as e:
        raise HTTPException(429, str(e))

    if not user.totp_secret or not _verify_code(user.totp_secret, body.code):
        record_mfa_login_failure(user.id)
        raise HTTPException(400, "Incorrect code. Check your authenticator app and try again.")

    record_mfa_login_success(user.id)
    user.totp_enabled = True
    audit.log(db, user.tenant_id, "mfa_enabled", user.id, detail={"via": "login_enforced"})
    audit.log(db, user.tenant_id, "user_logged_in", user.id, detail={"mfa": True})
    db.commit()
    notify_owners(
        tenant_admin_emails(db, user.tenant_id, exclude_user_id=user.id),
        "Sign-in to your Meridian workspace",
        f"{user.email} ({user.role}) just signed in to your Meridian workspace.",
    )
    token = create_access_token(user.id, user.tenant_id, user.role)
    return {
        "access_token": token, "token_type": "bearer",
        "tenant_id": user.tenant_id, "user_id": user.id, "role": user.role,
    }


# ---------- Email recovery (see module docstring, #3) ----------

class RecoveryRequestBody(BaseModel):
    pre_auth_token: str


class RecoveryRequestOut(BaseModel):
    masked_email: str


@router.post("/recovery/request", response_model=RecoveryRequestOut)
def request_recovery(body: RecoveryRequestBody, db: Session = Depends(get_db)):
    """Reachable only with a pre_auth_token from a successful password
    check (POST /auth/login's mfa_verify path, mfa_setup_required=False) -
    deliberately NOT a bare "enter your email" form, so this can't be used
    to enumerate accounts or spam an arbitrary address. Mints a SEPARATE,
    longer-lived (RECOVERY_TTL_SECONDS) token with its own purpose, rather
    than just extending the mfa_verify token's life - a stolen mfa_verify
    token should still only be redeemable at /verify-login, never here."""
    claims = decode_pre_auth_token(body.pre_auth_token, expected_purpose="mfa_verify")
    user = db.query(User).filter_by(id=claims["sub"], tenant_id=claims["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "Invalid login attempt.")
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    recovery_token = create_pre_auth_token(
        user.id, user.tenant_id, purpose="mfa_recovery", ttl_seconds=RECOVERY_TTL_SECONDS,
    )
    send_mfa_recovery_email(user.email, _recovery_url(tenant, recovery_token))
    audit.log(db, user.tenant_id, "mfa_recovery_requested", user.id)
    return RecoveryRequestOut(masked_email=_mask_email(user.email))


class RecoveryRedeemBody(BaseModel):
    token: str


@router.post("/recovery/redeem")
def redeem_recovery(body: RecoveryRedeemBody, db: Session = Depends(get_db)):
    """Public - reached from the emailed link with no session at all.
    Disables the lost authenticator (mirrors what an admin does by hand
    today: remove + re-add a locked-out teammate) rather than issuing a
    session directly - the next login re-enrolls a fresh one through the
    ordinary mfa_setup_required path, so this endpoint's blast radius if
    the link itself leaked is "one more MFA setup prompt", never a free
    session. A SECURITY-REDUCING action - see the frontend's own
    confirm-click requirement (app/mfa-recovery/page.tsx) for why this
    must never fire from an automated link-scanner's prefetch."""
    claims = decode_pre_auth_token(body.token, expected_purpose="mfa_recovery")
    user = db.query(User).filter_by(id=claims["sub"], tenant_id=claims["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "This link has expired. Please sign in again.")

    user.totp_enabled = False
    user.totp_secret = None
    audit.log(db, user.tenant_id, "mfa_recovery_used", user.id)
    db.commit()

    # A security-reducing action taken with no MFA proof at all (by
    # design - that's the whole point) - the tenant's other admin(s)
    # should know about this immediately, not just find it in the audit
    # log later. Excludes the user themselves, same as every other
    # owner-notification here.
    notify_owners(
        tenant_admin_emails(db, user.tenant_id, exclude_user_id=user.id),
        f"Two-factor authentication reset for {user.email}",
        f"{user.email} used the email-recovery link to disable their lost authenticator - "
        f"they'll be prompted to set up a new one on next sign-in. If this wasn't them, "
        f"someone else may have access to their email or password; reset their password "
        f"from the Team page right away.",
    )
    return {"status": "disabled"}
