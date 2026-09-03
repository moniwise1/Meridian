# Deploying to Railway

Two services from one GitHub repo (`moniwise1/Meridian`) — a `backend`
(FastAPI, Dockerfile-built) and a `frontend` (Next.js, Dockerfile-built) —
plus, optionally, a managed Postgres database for the backend's own
metadata store. Everything below is done in Railway's web dashboard; there
is no CLI step required (the CLI install proved unreliably slow in this
project's own dev environment — the dashboard flow is what's used here).

**Every step that needs your Railway login, your GitHub authorization, or
any secret (API keys, signing keys) has to be done by you** — those aren't
things an assistant should ever type into a form on your behalf, agent or
not. What's below is written so you can do it in about 20 minutes without
needing to figure anything out as you go.

## 0. Prerequisites

- A Railway account (railway.app), signed in with GitHub
- This repo pushed to GitHub (already done — `moniwise1/Meridian`, `main`)
- Your `ANTHROPIC_API_KEY` (console.anthropic.com) — Ask/Risk scan's
  insight explanations don't run without it; Risk scan's anomaly
  *detection* itself is deterministic pandas/numpy and works without it,
  but every "why does this matter" explanation needs a real key
- Your Paystack secret/public keys and a plan code, if you're turning on
  billing now (`app/billing/paystack.py`) — safe to leave blank and add
  later; `require_active_subscription` will just block Ask/Risk-scan/new
  connections until a tenant's `subscription_status` is set, which you can
  also do manually from the platform admin panel regardless of Paystack

## 1. New Project → deploy the backend

1. Railway dashboard → **New Project** → **Deploy from GitHub repo** →
   select `moniwise1/Meridian`.
2. Railway will try to build the repo root — before it does, open the new
   service's **Settings**, and under **Source**, set **Root Directory** to
   `backend`. It will then detect `backend/Dockerfile` and
   `backend/railway.json` (healthcheck at `/health`, restart-on-failure)
   on its own.
3. Rename the service to `backend` (Settings → General) so the next steps
   aren't ambiguous.

### Metadata database: pick one

The backend's own metadata (tenants, users, connections, audit log — never
customer data) needs somewhere to live. Two options:

**A — Railway Postgres (recommended for anything beyond a demo).** In the
same project: **New** → **Database** → **Add PostgreSQL**. Railway creates
it and exposes a `DATABASE_URL` reference variable you can point the
backend at (step 4 below) — no code change needed, `app/db/session.py`
already normalizes the `postgres://` scheme Railway uses. This is what
makes the metadata store survive a redeploy and, later, support more than
one backend instance — SQLite-on-a-volume (option B) only ever works for a
single instance, same limitation already documented for the in-process
rate limiter and login cooldown.

**B — SQLite on a Volume (fastest to get live today, single-instance
only).** Backend service → **Settings** → **Volumes** → **New Volume**,
mount path `/app/data`. This is exactly what the Dockerfile already
defaults `METADATA_DB_URL` to, so no extra env var is needed for this
path.

## 2. Backend environment variables

Backend service → **Variables**. Add these (values in `<>` are yours to
fill in — never paste a real secret into chat asking me to do this step for
you):

```
APP_SECRET_KEY=<generate below>
JWT_SECRET_KEY=<generate below, different from APP_SECRET_KEY>
PLATFORM_JWT_SECRET=<generate below, different from both above>
ANTHROPIC_API_KEY=<your key>
FRONTEND_ORIGIN=<filled in at step 5, once the frontend has a domain>
```

Generate each secret locally (run three times, three different keys):

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

If you added Railway Postgres in step 1: click **Variables** → **New
Variable** → **Add Reference** → pick the Postgres service's
`DATABASE_URL`, but rename the variable to `METADATA_DB_URL` on this
service (Railway lets you reference another service's variable under a
different name). If you're on SQLite-on-a-Volume instead, skip this — the
Dockerfile's default already points at the mounted volume.

Optional, add now or later:

```
PAYSTACK_SECRET_KEY=<from Paystack dashboard>
PAYSTACK_PUBLIC_KEY=<from Paystack dashboard>
PAYSTACK_PLAN_CODE=<from Paystack dashboard>
PAYSTACK_PLAN_AMOUNT=<smallest currency unit — kobo/cents — must match the plan>
KMS_PROVIDER=aws          # only if you're turning on AWS KMS now — see docs/CLOUD_KMS.md
AWS_KMS_KEY_ID=<...>
AWS_REGION=<...>
```

Do **not** set `PORT` — Railway assigns it automatically and the
Dockerfile's `CMD` already reads `$PORT`.

Railway redeploys automatically on every variable change, so the backend
will restart (and fail its healthcheck, harmlessly) after each edit here
until `FRONTEND_ORIGIN` is filled in in step 5 — that's expected.

## 3. Generate the backend's public domain

Backend service → **Settings** → **Networking** → **Generate Domain**.
Copy the resulting `https://<something>.up.railway.app` — the frontend
needs it next.

## 4. New service → deploy the frontend

1. In the same project: **New** → **GitHub Repo** → same repo again.
2. **Settings** → **Source** → **Root Directory** → `frontend`. Detects
   `frontend/Dockerfile` and `frontend/railway.json` the same way.
3. Rename the service to `frontend`.
4. **Variables** → add:
   ```
   NEXT_PUBLIC_API_BASE=https://<backend-domain-from-step-3>
   ```
   This one is baked into the client JS bundle at *build* time (Next.js
   inlines `NEXT_PUBLIC_*` values — see the comment in
   `frontend/Dockerfile`), which is why it has to be set before the first
   deploy rather than patched in afterward; Railway passes service
   Variables through as Docker build args automatically, so no extra
   config is needed for that to take effect.
5. **Settings** → **Networking** → **Generate Domain**. Copy this one too.

## 5. Close the loop: tell the backend about the frontend

Back on the **backend** service → **Variables** → set:

```
FRONTEND_ORIGIN=https://<frontend-domain-from-step-4>
```

This is what CORS checks against (`app/main.py`) — until it's set to the
real frontend origin, the browser will block every API call with a CORS
error even though the backend is up. Saving this variable triggers a
backend redeploy; give it a minute.

## 6. Bootstrap your own platform-admin account

Once both services show **Active**, create the first internal-admin
account the same way you did locally — this endpoint self-disables the
moment one exists, so this only works once:

```bash
curl -X POST https://<backend-domain>/platform/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"you@yourcompany.com","password":"<a real password, 8+ chars>"}'
```

Then sign in at `https://<frontend-domain>/platform/login`.

## 7. Smoke test

Same flow already verified locally:

1. `https://<frontend-domain>/login` → **Create account** → register a
   real (or test) tenant.
2. `https://<frontend-domain>/platform/tenants` (signed in as the staff
   account from step 6) → set that tenant's subscription to **active** —
   or wire up real Paystack billing first if you added those keys.
3. Back on the tenant app → **Data sources** → connect a real database.
4. **Risks** → **Scan for risks** — confirms the whole path (frontend →
   backend → your DB → back to the browser) actually works in production,
   not just locally.

## 8. Optional: a real domain instead of `*.up.railway.app`

Each service's **Settings** → **Networking** → **Custom Domain** — Railway
gives you a CNAME target to add at your DNS provider. Do this for the
frontend at minimum (`app.yourcompany.com`); the backend's Railway domain
is fine to keep as-is since customers never see it directly, though nothing
stops you from giving it one too (`api.yourcompany.com`) — just remember to
update `NEXT_PUBLIC_API_BASE` (frontend, triggers a rebuild) and
`FRONTEND_ORIGIN` (backend) to match if you do.

## Optional: Redis, before you scale the backend past one replica

The rate limiter, login cooldown, and query cache (`app/security/
rate_limit.py`, `login_cooldown.py`, `app/agents/query_cache.py`) fall
back to in-process memory by default — correct for the single-replica
backend this runbook sets up, silently weaker (each replica enforces its
own independent state) the moment you scale to more than one. Fixing that
is the same one-variable pattern as the Postgres addon above:

1. Same project → **New** → **Database** → **Add Redis**.
2. Backend service → **Variables** → **New Variable** → name it
   `REDIS_URL`, **Add Reference** → the Redis service's connection-string
   variable (its exact name varies — look for something like
   `REDIS_URL`/`REDISCLOUD_URL` in the reference picker, matching however
   Railway's Redis addon exposes it).
3. Save — triggers a redeploy. All three become genuinely global across
   every backend replica from that point on; no other config needed.

Skip this entirely if you're staying at one replica — nothing forces you
to add Redis before you actually need it, and every request still works
correctly without it, just scoped to that one instance instead of shared.

## What this does *not* solve

- **Real SMTP.** Invite-by-email and ticket-reply notifications still log
  to console output instead of sending — same gap as local dev, now just
  visible in Railway's deploy logs instead of your terminal.
- **Uptime monitoring.** Nothing here automatically probes the deployed
  URLs. Pair the frontend's `/status` page with a real external monitor
  (UptimeRobot, BetterStack, etc.) pointed at `https://<backend-domain>/health`
  before you rely on it.
