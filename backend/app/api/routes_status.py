"""
Public status page data - unauthenticated by design, the customer-facing
complement to routes_platform.py's staff-only incident management. Shows
the last 90 days of incidents (capped at 50 rows) so anyone can see recent
uptime/incident history without needing an account.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import SystemIncident, IncidentUpdate

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
def public_status(db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(days=90)
    incidents = (
        db.query(SystemIncident)
        .filter(SystemIncident.started_at >= cutoff)
        .order_by(SystemIncident.started_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for i in incidents:
        updates = (
            db.query(IncidentUpdate).filter_by(incident_id=i.id)
            .order_by(IncidentUpdate.created_at.asc()).all()
        )
        out.append({
            "id": i.id, "title": i.title, "status": i.status, "severity": i.severity,
            "started_at": i.started_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "updates": [
                {"status": u.status, "body": u.body, "created_at": u.created_at.isoformat()}
                for u in updates
            ],
        })
    ongoing = [i for i in incidents if i.status != "resolved"]
    return {"operational": len(ongoing) == 0, "incidents": out}
