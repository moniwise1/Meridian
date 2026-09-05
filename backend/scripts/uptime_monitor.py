"""
Automated uptime monitor - run this on a schedule (a Railway Cron Job,
every 5 minutes recommended) as its own standalone service, separate from
the main API/frontend services. See docs/UPTIME_MONITORING.md for the
Railway setup steps.

Deliberately a plain script, not a background thread inside the FastAPI
app: this app has no in-process scheduler by design (see
app/api/routes_monitor.py's docstring), and running the check FROM
OUTSIDE the API process is also the whole point - if the API process
itself is fully down, an in-process check could never even run to notice
that. A separate process checking the live public URLs from the outside
is what actually proves the site works the way a real visitor would
experience it, not just "the process is technically alive".

Stateless between runs by design (a Cron Job gets a fresh container each
time, no persisted memory of the previous run) - all the "is this a NEW
outage or the same ongoing one" logic lives server-side in
routes_monitor.py's heartbeat handler, keyed off whether an unresolved
auto-incident already exists. This script's only job each run is: check,
then report what it saw.

Required environment variables (set these on the Cron Job service, not
the main API service - it's the one place they're actually used):
  MONITOR_FRONTEND_STATUS_URL  e.g. https://www.getmeridiananalytics.com/status
  MONITOR_API_BASE_URL         e.g. https://<your-backend>.up.railway.app
  UPTIME_MONITOR_SECRET        same value as the API service's own setting
"""
import os
import sys
import httpx

TIMEOUT_SECONDS = 10.0


def _check(url: str) -> tuple[bool, str]:
    """Returns (ok, detail) - never raises; a network error is exactly as
    much "unhealthy" as a bad status code, both are things a real visitor
    would also experience as the site being down."""
    try:
        resp = httpx.get(url, timeout=TIMEOUT_SECONDS)
        if resp.status_code >= 200 and resp.status_code < 300:
            return True, f"{url} -> {resp.status_code}"
        return False, f"{url} -> {resp.status_code}"
    except httpx.HTTPError as e:
        return False, f"{url} -> {type(e).__name__}: {e}"


def main() -> int:
    frontend_url = os.environ.get("MONITOR_FRONTEND_STATUS_URL", "").strip()
    api_base = os.environ.get("MONITOR_API_BASE_URL", "").strip().rstrip("/")
    secret = os.environ.get("UPTIME_MONITOR_SECRET", "").strip()

    missing = [name for name, val in [
        ("MONITOR_FRONTEND_STATUS_URL", frontend_url),
        ("MONITOR_API_BASE_URL", api_base),
        ("UPTIME_MONITOR_SECRET", secret),
    ] if not val]
    if missing:
        print(f"[uptime_monitor] missing required env var(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    frontend_ok, frontend_detail = _check(frontend_url)
    api_ok, api_detail = _check(f"{api_base}/health")

    healthy = frontend_ok and api_ok
    failed_checks = []
    if not frontend_ok:
        failed_checks.append("frontend_status_page")
    if not api_ok:
        failed_checks.append("backend_health")

    detail = " | ".join([frontend_detail, api_detail])
    print(f"[uptime_monitor] healthy={healthy} {detail}")

    try:
        resp = httpx.post(
            f"{api_base}/monitor/heartbeat",
            json={"healthy": healthy, "check": ",".join(failed_checks) or "all", "detail": detail},
            headers={"X-Monitor-Secret": secret},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        print(f"[uptime_monitor] reported ok: {resp.json()}")
    except httpx.HTTPError as e:
        # The check itself still ran and printed its result above (visible
        # in the Cron Job's own logs either way) - only the REPORTING step
        # failed here, which is a real problem with this job specifically
        # (wrong secret, backend unreachable for a different reason than
        # the check just measured, etc.), worth a non-zero exit so
        # Railway's own cron-job failure tracking notices.
        print(f"[uptime_monitor] failed to report heartbeat: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
