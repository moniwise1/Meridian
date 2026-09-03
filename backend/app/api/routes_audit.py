from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import AuditLog
from app.security.auth import get_current_user, AuthContext
from app.audit.logger import verify_chain

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(limit: int = 100, db: Session = Depends(get_db),
               ctx: AuthContext = Depends(get_current_user)):
    rows = (
        db.query(AuditLog)
        .filter_by(tenant_id=ctx.tenant_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id, "timestamp": r.timestamp.isoformat(), "action": r.action,
            "status": r.status, "connection_id": r.connection_id, "query_id": r.query_id,
            "detail": r.detail, "entry_hash": r.entry_hash,
        }
        for r in rows
    ]


@router.get("/verify")
def verify_audit(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    """Recomputes the tenant's audit hash chain and reports whether it's
    intact — see app/audit/logger.py for exactly what this does and doesn't
    prove."""
    return verify_chain(db, ctx.tenant_id)
