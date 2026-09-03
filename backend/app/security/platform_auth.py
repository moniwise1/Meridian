"""
Authentication for Meridian's OWN internal staff (support agents, ops, the
owner) - deliberately a separate system from app/security/auth.py's
tenant-scoped auth, not an extension of it.

Every route in the rest of this app is built around one invariant: the
caller can only ever act within their own tenant_id, derived from a
verified token, never trusted from the request body. Platform staff are
the one place that invariant is intentionally lifted - a platform route
can look across every tenant. That is exactly why this can't just be
"another role" bolted onto the existing User/get_current_user system:
a bug that let a forged or misrouted tenant token satisfy a platform check
would be a full cross-tenant data breach, not a normal permission bug.

Structural separation, not just a role flag:
- A different table (PlatformStaff vs. User) - no tenant_id column, no
  membership in any tenant's data at all.
- A different token claim shape ({"platform_staff_id", "role"}, no
  "tenant_id"/"sub" the way tenant tokens have) - so a tenant token
  literally can't satisfy require_platform_staff's payload checks, and a
  platform token can't satisfy get_current_user's, even before either
  dependency's own logic runs.
- A different signing secret (PLATFORM_JWT_SECRET, falling back to
  JWT_SECRET_KEY/APP_SECRET_KEY if unset - set it separately in
  production) - so a leaked tenant-signing secret alone doesn't let an
  attacker forge platform access, and vice versa.

No self-registration endpoint exists for PlatformStaff anywhere in this
app. See routes_platform.py's login/bootstrap endpoint for the only way
an account gets created: the very first one bootstraps from an
unauthenticated request specifically because no staff exist yet to
authenticate as; every one after that requires an existing "owner" to
create it.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt
import time

from app.config import settings
from app.db.session import get_db
from app.db.models import PlatformStaff
from app.security.auth import hash_password, verify_password  # PBKDF2 helpers - not tenant-specific

_bearer = HTTPBearer(auto_error=False)

_PLATFORM_JWT_SECRET = (
    settings.platform_jwt_secret or settings.jwt_secret_key or settings.app_secret_key
)


def create_platform_access_token(staff_id: str, role: str, ttl_seconds: int = 60 * 60 * 12) -> str:
    payload = {
        "platform_staff_id": staff_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, _PLATFORM_JWT_SECRET, algorithm="HS256")


class PlatformAuthContext:
    def __init__(self, staff_id: str, role: str):
        self.staff_id = staff_id
        self.role = role


def get_current_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> PlatformAuthContext:
    if creds is None:
        raise HTTPException(401, "Missing bearer token.")
    try:
        payload = jwt.decode(creds.credentials, _PLATFORM_JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired, please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid session token.")

    staff_id = payload.get("platform_staff_id")
    if not staff_id:
        # A well-formed tenant token, signed with the same fallback secret
        # (e.g. both unset in a dev environment), would decode successfully
        # here but has no platform_staff_id claim - reject explicitly
        # rather than falling through.
        raise HTTPException(401, "Not a platform session token.")

    staff = db.query(PlatformStaff).filter_by(id=staff_id).first()
    if not staff:
        raise HTTPException(401, "Staff account no longer exists.")

    return PlatformAuthContext(staff_id=staff.id, role=staff.role)


def require_staff_role(*allowed_roles: str):
    def _dep(ctx: PlatformAuthContext = Depends(get_current_staff)) -> PlatformAuthContext:
        if ctx.role not in allowed_roles:
            raise HTTPException(403, f"This action requires one of: {', '.join(allowed_roles)}.")
        return ctx
    return _dep
