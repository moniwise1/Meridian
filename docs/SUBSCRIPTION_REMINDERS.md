# Subscription-expiry reminders (Railway Cron Job setup)

When a tenant subscribes, they now get a confirmation (an in-app notice in
the dashboard's notification bell, plus an email). This adds the other
half: a "your subscription renews in 7 days" reminder before each renewal
date, through the same notice + email path.

Sending it needs something on a timer. This app has no in-process
scheduler by design (same reasoning as `docs/UPTIME_MONITORING.md` and the
admin-triggered audit-anchor checkpoints) — so, exactly like the uptime
monitor, a small script (`backend/scripts/subscription_reminders.py`)
running on a schedule calls one server endpoint
(`POST /notifications/reminders/run`, `backend/app/api/routes_notifications.py`)
that does the real work: find every active subscription expiring within
the window, send each one reminder, and record that it was sent so the
next day's run doesn't send it again.

## 1. Generate a reminder secret

Any long random string — this authenticates the script to the endpoint,
the same "machine, not a login" auth as the uptime monitor and the
Paystack webhook. Generate one, don't reuse a secret from anywhere else:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. Add it to the backend service

Railway → your **backend** service → Variables → add:

```
SUBSCRIPTION_REMINDER_SECRET=<the value you just generated>
```

Optional, same service, if you want a different lead time than 7 days:

```
SUBSCRIPTION_EXPIRY_REMINDER_DAYS=7
```

Until `SUBSCRIPTION_REMINDER_SECRET` is set, `/notifications/reminders/run`
returns `503` unconditionally — a deployment that hasn't set this up can't
have a stray or guessed request trigger a reminder sweep.

## 3. Create the Cron Job service

Railway → your project → **+ New** → **Cron Job** (a separate service, not
a deployment of the existing backend). Point it at the same repo/branch as
your backend service, with:

- **Command**: `python scripts/subscription_reminders.py`
- **Root directory**: `backend` (same as your backend service, so its
  Python environment already matches — no extra install step)
- **Schedule**: `0 9 * * *` (once a day, 09:00 UTC — the exact time
  doesn't matter; the reminder window is measured in whole days)

Add these variables on the **Cron Job service** (not the backend service —
these are only used here):

```
MERIDIAN_API_BASE_URL=https://<your-backend-service>.up.railway.app
SUBSCRIPTION_REMINDER_SECRET=<the same value from step 1>
```

## 4. Confirm it's actually working

Check the Cron Job's own logs after its first scheduled run (or trigger a
manual run from Railway's UI) — you should see:

```
[subscription_reminders] ok: checked=<n> reminded=<m>
```

`checked` is how many active subscriptions have a known renewal date;
`reminded` is how many got a fresh reminder this run (0 is normal — it
only sends inside the 7-day window, and only once per renewal period).

To see the whole path end to end: give a test tenant an
`subscription_expires_at` a few days out with `subscription_status =
'active'`, run the job manually, and confirm the admin gets the email and
sees the notice in the bell — a second manual run the same day should
report `reminded=0` (it won't re-send).

## What this does and doesn't give you

**Does**: a reliable once-per-period heads-up before every renewal, in-app
and by email, plus the one-time confirmation when a subscription first
activates (that part is automatic in the billing flow — no cron needed).

**Doesn't**: dunning / retry orchestration for a *failed* renewal payment
(Paystack handles the retry cadence itself; this app just surfaces the
`invoice.payment_failed` webhook as its own notice + email). Sub-day
timing precision. If the Cron Job service is down for a day, that day's
reminders are simply skipped — they are not queued and caught up, though
the next day's run still catches anyone who has since moved *into* the
window.
