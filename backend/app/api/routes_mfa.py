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
   here, at `/verify-login` or `/setup-login` + `/confirm-login`.

Secrets are encrypted at rest via `app/security/secrets.py` - the same
backend that protects connected-database credentials - so a metadata-DB
leak alone isn't enough to generate valid codes for every user; someone
would also need whatever decrypts it (the local Fernet key, or real AWS
KMS access in production).

Login-time code guessing is rate-limited the same way password guessing
already is (`app/security/login_cooldown.py`'s dedicated mfa guard) -
a 6-digit code is a much smaller space than a password.

NOT built: backup/recovery codes for a lost authenticator device. A user
who loses their device and has no admin available to help currently has
no self-service way back in - see the Security page's copy, which says
this plainly rather than pretending a recovery flow exists. An admin CAN
always get someone back in by removing then re-adding them as a teammate
(a new account has totp_enabled=False), or - if admin themselves is
locked out - via a platform-staff comp/support path, same as any other
account-recovery gap in this app that has no email-sending identity to
build a real "reset link" flow on top of (see
`app/agents/email_delivery.py` for why).
"""
import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
from app.agents.notifications import notify_owners

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

ISSUER = "Meridian"


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
