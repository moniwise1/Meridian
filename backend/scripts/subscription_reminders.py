"""
Subscription-expiry reminder trigger - run this on a schedule (a Railway
Cron Job, once a day) as its own standalone service, separate from the
main API/frontend services. See docs/SUBSCRIPTION_REMINDERS.md for the
Railway setup steps.

Deliberately a plain script that just calls one HTTP endpoint, not a
background thread inside the FastAPI app: this app has no in-process
scheduler by design (same reasoning as scripts/uptime_monitor.py and the
admin-triggered audit-anchor checkpoints). All the real work - who is due
a reminder, sending the in-app notice + email, and the once-per-period
idempotency - lives server-side in
app/api/routes_notifications.py's `/notifications/reminders/run`. This
script's only job each run is: call that endpoint, print what it did.

Stateless between runs by design (a Cron Job gets a fresh container each
time). Safe to run more than once a day - a second run is a near-total
no-op server-side.

Required environment variables (set these on the Cron Job service, not
the main API service - it's the one place they're actually used):
  MERIDIAN_API_BASE_URL         e.g. https://<your-backend>.up.railway.app
  SUBSCRIPTION_REMINDER_SECRET  same value as the API service's own setting
"""
import os
import sys
import httpx

TIMEOUT_SECONDS = 30.0


def main() -> int:
    api_base = os.environ.get("MERIDIAN_API_BASE_URL", "").strip().rstrip("/")
    secret = os.environ.get("SUBSCRIPTION_REMINDER_SECRET", "").strip()

    missing = [name for name, val in [
        ("MERIDIAN_API_BASE_URL", api_base),
        ("SUBSCRIPTION_REMINDER_SECRET", secret),
    ] if not val]
    if missing:
        print(f"[subscription_reminders] missing required env var(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        resp = httpx.post(
            f"{api_base}/notifications/reminders/run",
            headers={"X-Reminder-Secret": secret},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[subscription_reminders] request failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    body = resp.json()
    print(
        f"[subscription_reminders] ok: checked={body.get('checked')} "
        f"reminded={body.get('reminded')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
