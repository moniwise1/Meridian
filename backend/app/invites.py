"""
Real invite-by-email, shared between a tenant's team (kind="team",
app/api/routes_auth.py) and Meridian's own internal platform staff
(kind="staff", app/api/routes_platform.py) - the two flows are
structurally identical, so they're unified into one Invite table
(app/db/models.py) and one set of helpers here rather than duplicated.

An admin/owner names an email + role; a random token is emailed to that
address (never the row's own primary key, so it can't be enumerated);
the recipient proves control of that inbox and picks their OWN password
to accept. An un-accepted invite is worthless after INVITE_TTL_HOURS -
both a deliberate expiry AND explicitly revocable by an admin/owner
before that.

No background scheduler exists in this app (see app/config.py's audit-
anchor-github settings comment for the same constraint elsewhere) -
expiry is enforced LAZILY, checked wherever an invite is read, not by a
cron sweeping the table. A "pending" row past its expires_at is treated
as expired the moment anything here looks at it, and is flipped to
status="expired" in that same read so a stale invite never keeps
showing as "pending" in an admin's own invite list either.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import Invite

INVITE_TTL_HOURS = 24


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_invite(db: Session, kind: str, email: str, role: str, invited_by: str,
                   invited_by_email: str, tenant_id: str | None = None) -> tuple[Invite, str]:
    """Returns (invite, raw_token) - the raw token is handed to the caller
    ONCE, to put in the email, and is never stored or returned again."""
    token = secrets.token_urlsafe(32)
    invite = Invite(
        kind=kind, tenant_id=tenant_id, email=email.strip().lower(), role=role,
        token_hash=_hash_token(token), invited_by=invited_by, invited_by_email=invited_by_email,
        expires_at=datetime.utcnow() + timedelta(hours=INVITE_TTL_HOURS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, token


def _lazily_expire(db: Session, invite: Invite) -> Invite:
    if invite.status == "pending" and invite.expires_at < datetime.utcnow():
        invite.status = "expired"
        db.commit()
        db.refresh(invite)
    return invite


def get_invite_by_token(db: Session, kind: str, token: str) -> Invite | None:
    invite = db.query(Invite).filter_by(kind=kind, token_hash=_hash_token(token)).first()
    if not invite:
        return None
    return _lazily_expire(db, invite)


def list_invites(db: Session, kind: str, tenant_id: str | None = None) -> list[Invite]:
    """For an admin/owner's own "pending invites" list - also sweeps every
    stale pending row to "expired" as a side effect of listing."""
    q = db.query(Invite).filter_by(kind=kind)
    if tenant_id is not None:
        q = q.filter_by(tenant_id=tenant_id)
    invites = q.order_by(Invite.created_at.desc()).all()
    return [_lazily_expire(db, inv) for inv in invites]


def count_pending(db: Session, kind: str, tenant_id: str | None = None) -> int:
    """Counts only genuinely still-pending invites (lazily expiring first)
    - used alongside real accounts for seat-limit checks, so a stack of
    long-expired invites never wrongly counts against a plan's cap."""
    return sum(1 for inv in list_invites(db, kind, tenant_id) if inv.status == "pending")


def revoke_invite(db: Session, invite: Invite) -> None:
    invite.status = "revoked"
    db.commit()


def mark_accepted(db: Session, invite: Invite) -> None:
    invite.status = "accepted"
    invite.accepted_at = datetime.utcnow()
    db.commit()
