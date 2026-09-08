# Subscription reminders

## The short version

**There is nothing you have to set up.**

- When someone subscribes, they get a confirmation straight away — a notice
  in the dashboard's notification bell and an email.
- Before each renewal, they get a "renews in 7 days" heads-up — same notice
  + email. This fires automatically whenever anyone on that team has the
  dashboard open during the 7-day window (the notification bell checks for
  it on its own).

For a small team that logs in regularly, that's enough and needs zero
configuration.

## Optional: guarantee the daily timing with a cron

The automatic path above only fires when someone opens the app. If a
customer's whole team goes a week without logging in right before their
renewal, they'd miss the heads-up. If you want a hard guarantee, add a
once-a-day trigger that calls `POST /notifications/reminders/run` — it does
the same thing on a fixed schedule regardless of who's logged in. It shares
the same once-per-renewal guard, so it can never double-send with the
automatic path.

### Step 1 — make a secret and give it to the backend

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output. **Railway → your backend service → Variables**, add:

```
SUBSCRIPTION_REMINDER_SECRET=<the value you just generated>
```

Redeploy the backend. (Optional, same place: `SUBSCRIPTION_EXPIRY_REMINDER_DAYS=7`
to change the lead time.)

Until this is set the endpoint returns `503`, so a stray request can't
trigger a sweep.

### Step 2 — pick ONE way to call it daily

**Option A — GitHub Action (no new infrastructure).** The workflow file is
already in the repo (`.github/workflows/subscription-reminders.yml`). Give
GitHub the two values it needs: **repo → Settings → Secrets and variables →
Actions → New repository secret**, twice:

| Name | Value |
|---|---|
| `SUBSCRIPTION_REMINDER_SECRET` | the same value from Step 1 |
| `MERIDIAN_API_BASE_URL` | your backend URL, e.g. `https://<backend>.up.railway.app` (no trailing slash) |

GitHub then runs it daily at 09:00 UTC. Test it: **Actions tab →
Subscription reminders → Run workflow**; a green run ending in `HTTP 200`
and `{"checked":n,"reminded":m}` means it works (`reminded: 0` is normal —
it only sends inside the 7-day window).

**Option B — Railway Cron Job.** Railway → project → **+ New → Cron Job**,
same repo/branch, Root Directory `backend`, Start Command
`python scripts/subscription_reminders.py`, Cron Schedule `0 9 * * *`. On
that Cron Job service's Variables, set `MERIDIAN_API_BASE_URL` and
`SUBSCRIPTION_REMINDER_SECRET` (same value as Step 1). Its logs should show
`[subscription_reminders] ok: checked=n reminded=m`.

## What this doesn't do

- It's not dunning. A *failed* renewal payment is separate — Paystack runs
  its own retry cadence, and the app surfaces the `invoice.payment_failed`
  webhook as its own notice + email.
- The cron, if you add one, doesn't queue-and-catch-up. A day the job
  doesn't run is a day skipped; the next run still catches anyone who has
  since moved into the window.
