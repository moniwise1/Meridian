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
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


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
        payload = jwt.decode(creds.credentials, settings.app_secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired, please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid session token.")

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
