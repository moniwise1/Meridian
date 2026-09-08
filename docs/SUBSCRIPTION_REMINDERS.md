# Subscription reminders (setup)

When a tenant subscribes, they get a confirmation right away — an in-app
notice in the dashboard's notification bell, plus an email. **That part is
automatic and needs no setup.**

This page is only about the other half: the **"your subscription renews in
7 days"** reminder that goes out before each renewal date.

## Why this needs setup at all

Sending that reminder needs something running on a timer, once a day. This
app deliberately has no built-in scheduler (same reasoning as the uptime
monitor). So one external thing has to call a single endpoint —
`POST /notifications/reminders/run` — once a day. Everything else (working
out who is due, sending the notice and email, making sure nobody gets
reminded twice for the same renewal) happens inside the app.

Two ways to do the daily call. **Pick one.** They hit the exact same
endpoint; the GitHub Action is less setup.

---

## Step 1 (both options): make a secret and give it to the backend

The secret is what stops a random person from triggering a reminder sweep.
Nobody types it by hand — generate one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output. In **Railway → your backend service → Variables**, add:

```
SUBSCRIPTION_REMINDER_SECRET=<the value you just generated>
```

Optional, same place, if you ever want a different lead time than 7 days:

```
SUBSCRIPTION_EXPIRY_REMINDER_DAYS=7
```

Until `SUBSCRIPTION_REMINDER_SECRET` is set on the backend, the endpoint
returns `503` and no reminder can fire — including by accident.

Redeploy the backend so it picks up the new variable.

---

## Step 2, Option A — GitHub Action (recommended, no new infrastructure)

The repo already has the workflow file
(`.github/workflows/subscription-reminders.yml`). You just give GitHub the
two values it needs.

**GitHub → your repo → Settings → Secrets and variables → Actions → New
repository secret.** Add two:

| Name | Value |
|---|---|
| `SUBSCRIPTION_REMINDER_SECRET` | the same value from Step 1 |
| `MERIDIAN_API_BASE_URL` | your backend's URL, e.g. `https://<your-backend>.up.railway.app` (no trailing slash) |

That's it. GitHub runs it every day at 09:00 UTC.

**Test it now:** GitHub → **Actions** tab → **Subscription reminders** (left
side) → **Run workflow** → **Run workflow**. Open the run; the log should
end with:

```
HTTP 200
{"checked":<n>,"reminded":<m>}
```

`checked` = how many active subscriptions have a renewal date. `reminded`
= how many got a reminder this run. **`reminded: 0` is completely normal** —
it only sends in the last 7 days before a renewal, and only once per
renewal.

> Note: GitHub disables scheduled workflows in a repo with no activity for
> 60 days. Not a concern while the repo is being worked on; if it ever goes
> fully idle, a single push (or a manual "Run workflow") re-enables it.

---

## Step 2, Option B — Railway Cron Job

Use this instead if you'd rather keep everything on Railway.

**Railway → your project → + New → Cron Job.** (This is a small scheduled
container, separate from your always-on backend service — it wakes up,
runs one command, exits.) Point it at the same GitHub repo and branch as
your backend, and set:

- **Root Directory:** `backend`
- **Start Command:** `python scripts/subscription_reminders.py`
- **Cron Schedule:** `0 9 * * *`

Then on **that Cron Job service** (not the backend service) → Variables:

```
MERIDIAN_API_BASE_URL=https://<your-backend>.up.railway.app
SUBSCRIPTION_REMINDER_SECRET=<the same value from Step 1>
```

**Test it:** trigger a manual run from the Cron Job's page. Its logs should
show:

```
[subscription_reminders] ok: checked=<n> reminded=<m>
```

---

## Seeing the whole thing work end to end (optional)

If you want to watch a real reminder go out rather than trust it blind:
take a test tenant, set its `subscription_status` to `active` and its
`subscription_expires_at` to 3 days from now, then run the job manually
(either option). The tenant's admin should get the email and see the notice
in the bell. Run it a second time the same day — it should report
`reminded: 0`, because it won't send the same reminder twice.

## What this doesn't do

- It's not dunning. A *failed* renewal payment is handled separately —
  Paystack does its own retry cadence, and the app surfaces the
  `invoice.payment_failed` webhook as its own in-app notice + email.
- If the scheduler is down for a day, that day's reminders are skipped, not
  queued and caught up. The next day's run still catches anyone who has
  since moved into the 7-day window.
