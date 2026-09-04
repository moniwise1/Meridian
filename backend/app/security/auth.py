"""
Authentication (replaces the earlier "seed a tenant/user by script" MVP
stand-in). This is real password hashing + signed session tokens - not an
external SSO/OAuth integration (that needs a real IdP app registration this
environment can't create), but it closes the more important gap: routes no
longer trust a tenant_id/user_id the client simply typed into the request
body. Every authenticated route now derives who's asking from a verified
token, per BUILD SPEC section 7 ("never trust tenant IDs supplied directly
by the client").
"""
import hashlib
import hmac
import os
import time
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import User, Tenant

_bearer = HTTPBearer(auto_error=False)

PBKDF2_ITERATIONS = 260_000

# Falls back to app_secret_key when JWT_SECRET_KEY isn't set, so existing
# deployments keep working unchanged. Split into its own setting (rather
# than reusing app_secret_key, which app/security/secrets.py's "local"
# backend also uses to encrypt stored DB credentials) so the two can be
# rotated independently - rotating the JWT secret invalidates every active
# session, which is a very different operational event from rotating the
# key that decrypts credentials, and conflating them meant you couldn't do
# one without doing the other.
_JWT_SECRET = settings.jwt_secret_key or settings.app_secret_key


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(candidate, expected)


def create_access_token(user_id: str, tenant_id: str, role: str, ttl_seconds: int = 60 * 60 * 12) -> str:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


# MFA login-time "pre-auth" token (app/api/routes_mfa.py): issued once a
# password has checked out but before a real session exists yet - the
# whole point of MFA is that a correct password alone must NOT be enough
# to get a usable session, so /auth/login hands back one of these instead
# of an access_token when the account needs a code. Deliberately a
# DIFFERENT claim shape (pre_auth=True, purpose=..., no "role") so it can
# never be mistaken for - or accepted as - a real session token; see the
# explicit rejection in get_current_user below. Short TTL (5 min default)
# since its only job is to survive the few seconds between "password
# accepted" and "code entered", not to be a usable credential on its own.
PRE_AUTH_TTL_SECONDS = 5 * 60


def create_pre_auth_token(user_id: str, tenant_id: str, purpose: str) -> str:
    payload = {
        "pre_auth": True,
        "purpose": purpose,  # "mfa_verify" | "mfa_setup"
        "sub": user_id,
        "tenant_id": tenant_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + PRE_AUTH_TTL_SECONDS,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def decode_pre_auth_token(token: str, expected_purpose: str) -> dict:
    """Returns {"sub": user_id, "tenant_id": tenant_id} or raises
    HTTPException(401) - used by the login-time MFA endpoints and by the
    cross-subdomain session handoff (app/api/routes_auth.py's
    /auth/handoff/redeem, purpose="handoff"), never by get_current_user
    (a pre-auth token is explicitly rejected there, see below)."""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "This login attempt has expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid login attempt.")
    if not payload.get("pre_auth") or payload.get("purpose") != expected_purpose:
        raise HTTPException(401, "Invalid login attempt.")
    return {"sub": payload["sub"], "tenant_id": payload["tenant_id"]}


class AuthContext:
    def __init__(self, user_id: str, tenant_id: str, role: str):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    if creds is None:
        raise HTTPException(401, "Missing bearer token.")
    try:
        payload = jwt.decode(creds.credentials, _JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired, please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid session token.")

    # A well-formed, validly-signed token that isn't a tenant token at all
    # - most notably a platform-staff token (app/security/platform_auth.py
    # uses a different claim shape on purpose) - decodes fine above but has
    # no "sub"/"tenant_id" claims. Reject cleanly here rather than letting
    # a raw KeyError turn into an unhandled 500; the security outcome is
    # the same either way (no access granted), but this is the honest,
    # intended failure path, not an accident.
    if "sub" not in payload or "tenant_id" not in payload:
        raise HTTPException(401, "Not a tenant session token.")

    # A pre-auth token (see create_pre_auth_token above) carries the same
    # "sub"/"tenant_id" claims a real session token does - MUST be
    # explicitly rejected here, or the whole point of withholding a real
    # session until MFA passes would be defeated by just using the
    # pre-auth token as if it were one. It's only ever redeemable at the
    # two dedicated login-time endpoints in app/api/routes_mfa.py.
    if payload.get("pre_auth"):
        raise HTTPException(401, "This login is not yet complete.")

    user = db.query(User).filter_by(id=payload["sub"], tenant_id=payload["tenant_id"]).first()
    if not user:
        raise HTTPException(401, "User no longer exists.")

    return AuthContext(user_id=user.id, tenant_id=user.tenant_id, role=user.role)


def require_role(*allowed_roles: str):
    def _dep(ctx: AuthContext = Depends(get_current_user)) -> AuthContext:
        if ctx.role not in allowed_roles:
            raise HTTPException(403, f"This action requires one of: {', '.join(allowed_roles)}.")
        return ctx
    return _dep


def require_active_subscription(
    ctx: AuthContext = Depends(get_current_user), db: Session = Depends(get_db),
) -> AuthContext:
    """Gates the core product actions behind an active, paid subscription
    (premium-from-onset model - see app/api/routes_billing.py). 402 Payment
    Required is the correct status for this, not 403: the caller is who
    they say they are and would be allowed to act, the account just isn't
    paid. Account/team/audit/billing screens deliberately do NOT depend on
    this, so an unpaid admin can still see their own org's status and pay."""
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    if not tenant or tenant.subscription_status != "active":
        raise HTTPException(402, "Your organization's subscription is not active. Visit Billing to subscribe.")
    return ctx
