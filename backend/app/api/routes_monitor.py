"""
Automated uptime monitoring - the real fix for the gap the status page's
own model docstring (SystemIncident, app/db/models.py) calls out plainly:
incidents there are logged by a human, "not automated multi-region uptime
probing". This app has no background job scheduler of its own (same
constraint as app/audit/anchor.py's checkpoint publishing) - genuinely
automated monitoring needs something OUTSIDE this API process, on a
timer, checking the live site from the outside the way a real visitor
would, independent of whether this process is even still running.

That's exactly what scripts/uptime_monitor.py + a Railway Cron Job give
us: a separate scheduled service that fetches the public status page and
this API's own /health, then reports the result here. This module is
just the reporting endpoint that script calls into - it does not do any
probing itself, and never runs anything on a timer by itself.

Authenticated by a shared secret (UPTIME_MONITOR_SECRET), not a human
platform-staff login - a scheduled script has no human to log in as. Same
category of "machine, not human" auth this app already uses elsewhere:
the Paystack webhook's HMAC signature, the GitHub token behind audit
anchoring. Compared with hmac.compare_digest (constant-time), same
reasoning as every other secret-comparison in this app - a naive `==`
leaks timing information about how many leading characters matched.
"""
import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import SystemIncident, IncidentUpdate
from app.audit import logger as audit

router = APIRouter(prefix="/monitor", tags=["monitor"])

# A fixed, recognizable title so heartbeat runs can find "the" open
# auto-incident (there should only ever be one at a time) without
# depending on remembering an id across scheduled runs, which are
# stateless by design - each run of scripts/uptime_monitor.py knows
# nothing about the previous one except what it can look up here.
AUTO_INCIDENT_TITLE = "Automated check detected an outage"


def _verify_secret(x_monitor_secret: str | None = Header(default=None)) -> None:
    if not settings.uptime_monitor_secret:
        raise HTTPException(503, "Uptime monitoring is not configured on this deployment.")
    if not x_monitor_secret or not hmac.compare_digest(x_monitor_secret, settings.uptime_monitor_secret):
        raise HTTPException(401, "Invalid monitor secret.")


class HeartbeatRequest(BaseModel):
    healthy: bool
    # Which check(s) failed, e.g. "backend_health" or
    # "frontend_status_page,backend_health" - free text describing what
    # scripts/uptime_monitor.py actually observed, not a fixed enum, so
    # the incident body stays honest about exactly what was checked.
    check: str
    detail: str = ""


class HeartbeatResult(BaseModel):
    action: str  # "no_change" | "incident_opened" | "incident_resolved"
    incident_id: str | None = None


@router.post("/heartbeat", response_model=HeartbeatResult, dependencies=[Depends(_verify_secret)])
def report_heartbeat(body: HeartbeatRequest, db: Session = Depends(get_db)) -> HeartbeatResult:
    """Called on every scheduled run (see docs/UPTIME_MONITORING.md for
    the recommended interval). Idempotent by design, since a scheduled
    script has no memory between runs: opens a new incident the first
    time a check fails, does nothing on every subsequent failing run
    while that same incident is still open (never spams duplicate
    incidents for one ongoing outage), and auto-resolves it the first
    time a check passes again after having been open. created_by_staff_id
    is left null - that column already permits it, and null here is
    exactly what distinguishes "automated" from "a human logged this" in
    the platform Activity view."""
    open_incident = (
        db.query(SystemIncident)
        .filter_by(title=AUTO_INCIDENT_TITLE, created_by_staff_id=None)
        .filter(SystemIncident.status != "resolved")
        .order_by(SystemIncident.started_at.desc())
        .first()
    )

    if not body.healthy:
        if open_incident:
            # Same outage still ongoing - nothing new to log. A future
            # run reporting a DIFFERENT check failing while this is still
            # open is deliberately treated the same way rather than
            # opening a second incident; add_incident_update below still
            # gives staff a way to note that by hand if it matters.
            return HeartbeatResult(action="no_change", incident_id=open_incident.id)

        incident = SystemIncident(title=AUTO_INCIDENT_TITLE, severity="critical", created_by_staff_id=None)
        db.add(incident)
        db.flush()
        db.add(IncidentUpdate(
            incident_id=incident.id, status="investigating",
            body=f"Automated monitoring detected a failure ({body.check}). {body.detail}".strip(),
        ))
        db.commit()
        audit.log(db, "platform", "uptime_incident_auto_opened", None,
                   detail={"incident_id": incident.id, "check": body.check})
        return HeartbeatResult(action="incident_opened", incident_id=incident.id)

    if open_incident:
        open_incident.status = "resolved"
        open_incident.resolved_at = datetime.utcnow()
        db.add(IncidentUpdate(
            incident_id=open_incident.id, status="resolved",
            body="Automated monitoring confirmed the site is responding normally again.",
        ))
        db.commit()
        audit.log(db, "platform", "uptime_incident_auto_resolved", None,
                   detail={"incident_id": open_incident.id})
        return HeartbeatResult(action="incident_resolved", incident_id=open_incident.id)

    return HeartbeatResult(action="no_change")
