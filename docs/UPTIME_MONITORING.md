# Automated uptime monitoring (Railway Cron Job setup)

The status page's incidents used to be entirely manual — a platform staffer
clicking "New incident" when something actually broke. This adds real
automated detection on top of the exact same incident model: a small script
(`backend/scripts/uptime_monitor.py`) checks the live public site from the
outside on a schedule, and reports what it finds to a new endpoint
(`POST /monitor/heartbeat`, `backend/app/api/routes_monitor.py`), which
opens or resolves an incident exactly the way a human would have.

This app has no in-process background scheduler by design (same reasoning
as the audit-anchor checkpoint publishing, which is admin-triggered for the
same reason) — genuine automated monitoring needs something running
*outside* the API process, on a timer, checking the live site the way a
real visitor would. A Railway Cron Job is exactly that: a separate,
independently-scheduled service in the same project.

## 1. Generate a monitor secret

Any long random string — this authenticates the script to the heartbeat
endpoint, the same way the Paystack webhook is authenticated by its own
signature rather than a login. Nobody types this in; generate one and
never reuse a secret you use anywhere else:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. Add it to the backend service

Railway → your **backend** service → Variables → add:

```
UPTIME_MONITOR_SECRET=<the value you just generated>
```

Until this is set, `/monitor/heartbeat` returns `503` unconditionally — a
deployment that hasn't set this up can't have a stray or guessed request
open fake incidents.

## 3. Create the Cron Job service

Railway → your project → **+ New** → **Cron Job** (a separate service, not
a deployment of the existing backend). Point it at the same repo/branch as
your backend service, with:

- **Command**: `python scripts/uptime_monitor.py`
- **Root directory**: `backend` (same as your backend service, so its
  Python environment/dependencies already match — no extra install step)
- **Schedule**: `*/5 * * * *` (every 5 minutes; adjust to taste — more
  frequent means faster detection, less frequent means fewer Railway
  cron-job runs billed)

Add these variables on the **Cron Job service** (not the backend service —
these are only used here):

```
MONITOR_FRONTEND_STATUS_URL=https://www.getmeridiananalytics.com/status
MONITOR_API_BASE_URL=https://<your-backend-service>.up.railway.app
UPTIME_MONITOR_SECRET=<the same value from step 1>
```

`MONITOR_API_BASE_URL` is your backend's own Railway-issued URL (or a
custom domain if you've mapped one to it) — the script checks
`{MONITOR_API_BASE_URL}/health` and reports to
`{MONITOR_API_BASE_URL}/monitor/heartbeat`.

## 4. Confirm it's actually working

Check the Cron Job's own logs after its first scheduled run (or trigger a
manual run from Railway's UI) — you should see a line like:

```
[uptime_monitor] healthy=True https://www.getmeridiananalytics.com/status -> 200 | https://<backend>.up.railway.app/health -> 200
[uptime_monitor] reported ok: {'action': 'no_change', 'incident_id': None}
```

To confirm the failure path for real (recommended once, so you're not
trusting this blind): temporarily point `MONITOR_API_BASE_URL` at a
nonexistent URL, trigger a manual run, and confirm a new incident appears
on `/status` and in the platform Activity page as `uptime_incident_auto_opened`
— then put the real URL back and confirm the next run resolves it
(`uptime_incident_auto_resolved`).

## What this does and doesn't give you

**Does**: real automated detection of your site being down, backed by the
exact same incident/status-page model a human update would use, with no
duplicate incidents for one ongoing outage and automatic resolution on
recovery.

**Doesn't**: alerting (email/SMS/Slack the moment something breaks) — this
only ever gets checked by someone looking at `/status` or the platform
Activity page. Multi-region checking (Railway Cron Jobs run from one
region). Sub-minute detection (Railway's cron scheduling is minute-grained
at best). For those, pair this with — or replace it with — a real
third-party monitor (UptimeRobot, Better Stack, Pingdom); this in-house
version exists because it needed no third-party account and plugs directly
into the incident model this app already has, not because it's a superset
of what a dedicated monitoring service gives you.
