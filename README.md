# Meridian — Secure AI Enterprise Analytics Agent

A user registers a company workspace, connects a real database with a
verified read-only credential, asks a business question in plain language,
and the agent finds the right data, analyses it, checks for anomalies,
investigates the most significant one, and explains the answer with
evidence — all without ever being able to write to the source database.

Everything described below was actually run and tested during development
against real PostgreSQL and MySQL/MariaDB instances, not just written as
comments. Where something is a stand-in for infrastructure this sandbox
doesn't have (SMTP, cloud KMS, an external IdP), that's called out
explicitly rather than glossed over.

## What's implemented

**Internal admin panel** (`app/security/platform_auth.py`,
`app/api/routes_platform.py`, `/platform/*` in the frontend) — a
completely separate app surface for Meridian's own team, not an extension
of the tenant-scoped app: separate login (`/platform/login`), separate
account table (`PlatformStaff`, not `User`), separate signing secret
(`PLATFORM_JWT_SECRET`), and a structurally different JWT claim shape, so a
tenant token and a platform token can never satisfy each other's auth
check even by accident. This is the one deliberate exception to "every
route is scoped to the caller's own tenant_id" — everywhere else in this
codebase, that's an invariant; here, cross-tenant visibility is the
explicit point, which is exactly why it needed its own identity system
rather than a role flag on the existing one. First-run bootstraps the one
and only "owner" account via `POST /platform/bootstrap`; every account
after that requires an existing owner to create it. That endpoint is
gated by **two** conditions, not one (a security-review fix): no staff
account may exist yet, AND the request must carry the correct
`PLATFORM_BOOTSTRAP_TOKEN`. "No staff yet" alone was never a real guard —
the source is public, so an attacker knows to race the bootstrap endpoint
against a fresh deployment, and winning it is a full cross-tenant breach.
With the token unset (the default) the endpoint is disabled outright
(`403`); you set it for the single deploy where you create the first
owner, then unset it. Verified end-to-end: token unset → `403` and no
account created; token set but wrong/missing in the request → `403`;
token set and correct → the first owner is created; and once any staff
account exists it's `403` regardless of the token.

Covers: browsing/editing/deleting tenants (with a cascading delete across
every tenant-scoped table, including — deliberately — that tenant's own
audit history, since this doubles as how a GDPR-style erasure request gets
fulfilled), a cross-tenant support ticket queue (customers file tickets at
`/support`, tenant-scoped like everything else customer-facing; staff see
and answer every tenant's tickets at `/platform/tickets`), a manually-
logged incident/status system in the same spirit as how Stripe/GitHub
status pages work (a human posts what's happening — not automated
multi-region uptime probing, which this deliberately doesn't attempt; pair
with a real monitoring tool for that) with a public, unauthenticated
`GET /status` endpoint, and a rough internal health snapshot.

Verified with a full HTTP round trip through the real app, specifically
targeting the boundary that matters most: a tenant token is rejected on
every `/platform/*` route (401) and a platform token is rejected on every
tenant route (401) — including a real bug this caught and fixed, where a
platform token handed to the tenant-scoped `get_current_user` raised an
unhandled `KeyError` (missing `sub`/`tenant_id` claims) instead of a clean
401; same security outcome either way, but now an intentional failure path
instead of an accidental one. Also verified: cross-tenant ticket isolation,
the tenant-deletion cascade, and the public status page correctly flipping
`operational` based on open incidents.

Staff can now be role-changed and removed from the panel itself
(`PATCH`/`DELETE /platform/staff/{id}`, owner-only, `/platform/staff`),
not just added — "owner" is full access, "support" is limited to tenants/
tickets/status. Both refuse to demote or delete the **last remaining
owner**: since `/platform/bootstrap` is a one-time, self-disabling
endpoint, zero owners would permanently lock everyone out of the panel
with no way back in short of restoring a database backup. A `GET
/platform/audit` + `/platform/audit/verify` pair (`/platform/audit` in the
nav) mirrors the tenant-facing `/audit` exactly, scoped to the synthetic
`"platform"` tenant_id every staff action is already logged under —
staff logins (previously not logged at all) plus every staff/tenant/
ticket/incident action, so "who did what and when" is answerable the same
way it already was for a tenant's own team. Verified end-to-end,
including the subtlety that demoting or deleting *the account whose own
session you're using* takes effect immediately on that same session (role
is re-checked from the database on every request, not cached from the
JWT) — confirmed by a test that hit exactly that behavior on its first
attempt and had to route around it, not by design intent alone.

The tenant side got the equivalent: `PATCH`/`DELETE /auth/users/{id}`
(admin-only, `/team`) let an admin change a teammate's role or remove
them, with the same last-admin protection (admin is required for team/
billing/data-source management, so zero admins would lock an organization
out of managing itself). `/team` never actually had an "add teammate" UI
before this round despite the backend endpoint existing — it does now,
alongside the free-tier 1-account cap.

Caught and fixed a real, already-deployed regression while building this:
adding `created_at: str` to `UserOut` earlier (for the tier/sub-accounts
work) broke `PATCH /auth/users/{id}/row_scope`, which still returned the
raw ORM object relying on FastAPI's automatic serialization — a `str`
field can't absorb a `datetime` object, so every row-scope save was
silently 500ing in production. Found by actually exercising the endpoint
end-to-end rather than assuming an unrelated-looking change was safe.

Fixed a real report of a tenant that **couldn't be deleted from the
panel** — the "Permanently delete" button stayed greyed out no matter
what was typed into the confirm box. The delete confirmation requires
retyping the organization's name exactly (`confirmText === tenant.name`),
and `/auth/register` stored `company_name` verbatim — so a signup with a
stray leading or trailing space (`"Joelan "`) produced a name that's
impossible to reproduce by typing, since the padding is invisible in both
the input and the placeholder. Three-part fix: `/auth/register` now
`.strip()`s the company name before storing it (and rejects a
blank-after-strip name outright); the platform Tenants page compares
`confirmText.trim() === tenant.name.trim()`, so any already-affected row
can be confirmed by typing the visible name; and `PATCH
/platform/tenants/{id}` strips `name` too, which also gives a staffer a
way to repair an existing padded row by saving the visible name back over
it. Verified with a real SQLite + FastAPI round trip: a padded signup now
stores the trimmed name, a whitespace-only name is rejected, the trimmed
confirm gate accepts the visible name for a simulated legacy padded row,
and the `PATCH` path stores its name trimmed.

**Billing** (`app/billing/paystack.py`, `app/api/routes_billing.py`) —
premium-from-onset: a tenant is charged immediately on subscribe via
Paystack, not given a delayed-billing free trial, with a self-serve full
refund available if they cancel within `BILLING_REFUND_WINDOW_DAYS` (7 by
default) — after that window, cancelling stops future billing only, no
refund. Activation is reachable from two independent paths (the browser's
post-checkout redirect, and Paystack's async webhook) so either one alone
completes it. The core product actions (creating a data source, Ask, Risk
scan) are gated behind an active subscription via
`require_active_subscription` (402 Payment Required); account/team/audit/
billing screens deliberately are not, so an unpaid admin can still see
their org's status and pay. Every state transition goes through the same
hash-chained audit log as the rest of the app.

A security-review follow-up hardened the *other* activation path.
`GET /billing/verify?reference=…` (the browser's post-checkout redirect)
verified with Paystack that the reference *succeeded*, but never checked
it was *this tenant's* reference — so a tenant could pass any successful
reference (their own stale one, one leaked in a URL or a log) and
self-activate a paid subscription without paying. `/subscribe` already
records `result["reference"]` on the tenant before redirecting, so
`/verify` now requires the incoming reference to match that (and,
defence-in-depth, that any `metadata.tenant_id` Paystack echoes back
names this tenant); a mismatch is a `403` and an audit-logged
`subscription_verify_reference_mismatch`. Relatedly, `_activate` now
sets `Tenant.plan` by mapping the *verified* transaction's `plan_code`
back to our own plan key (`plan_key_for_paystack_code`), rather than
trusting the value `/subscribe` optimistically wrote before any payment.
The webhook path needed no change — it's authenticated by the signature
check below and attributes events by metadata / customer code. Verified
end-to-end (real SQLite + FastAPI): replaying another tenant's reference
is refused and does not activate the attacker; a tenant's own reference
activates and reconciles the plan; a tenant with no started checkout is
refused; the signed webhook still activates the right tenant; a bad
webhook signature is still `401`.

The webhook signature check (`verify_webhook_signature` — HMAC-SHA512 over
the raw request body, constant-time compared) is the one thing standing
between "a real payment happened" and "anyone who finds the webhook URL
can forge a paid-subscription event" — verified with real test vectors
(valid signature, wrong signature, forged-with-wrong-secret, tampered
body, re-serialized-but-logically-identical body) in addition to a full
HTTP round trip through the real app (subscribe → pay → gate blocks then
allows → webhook → cancel-with-refund inside the window → cancel-without-
refund outside it → audit trail intact throughout). Honest limitation:
none of it has been exercised against a live Paystack account (no test-
mode keys available in this environment) — built strictly to Paystack's
documented API contract, with the specific assumptions that couldn't be
verified called out in the module docstring. Confirm the first real
transaction in Paystack's own dashboard before trusting this in
production.

**Three real pricing tiers** (`app/billing/plans.py`) — Basic (₦5,000/mo),
Pro (₦9,999/mo), Premium (₦25,000/mo), each a genuinely separate Paystack
Plan object (`PAYSTACK_PLAN_CODE_BASIC`/`_PRO`/`_PREMIUM`, since Paystack's
own model is one price per plan — there's no single plan reused at three
prices). `GET /billing/plans` is the single source of truth the pricing
cards on `/billing` render from directly (price, feature bullets, seat/
connection limits) — not a second, hand-maintained copy of the same
numbers that could quietly drift from what's actually enforced. A plan
whose Paystack code isn't set yet reports `configured: false` and the
card shows "Not yet available" instead of a Subscribe button that would
fail confusingly deep into a real checkout attempt.
`backend/scripts/paystack_plans.py` creates the three plans on a Paystack
account (test or live) and prints the env vars; the full subscribe →
checkout → verify → webhook → cancel + refund lifecycle was exercised
end to end against the real Paystack test API on a live deploy. Going
from test to live is an env-var swap — `docs/BILLING_GO_LIVE.md`.

Deliberately honest about what differentiates the tiers: every paid plan
unlocks the identical product (Ask, Risk scan, document intelligence, row/
column access control, the full audit trail) — nothing here fakes a
feature gate just to make three cards look different. What genuinely
differs, and is actually enforced, is **seats** and **connected data
sources**: Basic 3/3, Pro 10/10, Premium unlimited/unlimited (free,
unchanged, stays at 1 seat and zero connections — it never reaches the
connection check at all, blocked earlier by `require_active_subscription`).
`Tenant.plan` (new column) tracks which specific plan a tenant is on,
deliberately kept a separate axis from the existing `Tenant.tier` property
(`tier` answers "are they paying at all" — still just "free"/"pro", used
everywhere the binary paywall gate already was; `plan` answers "which of
the three" and is what the seat/connection limits actually key off) so
changing one could never silently break the other.

**Monthly usage caps** (`app/billing/plans.py`, `app/billing/usage.py`) -
seats and connections aren't the only thing that now differs by tier:
Basic is capped at 50 questions and 20 report/presentation/export
downloads a month, Pro at 150/100, Premium unlimited/unlimited (free,
unchanged, never reaches either check - both `/ask` and artifact
generation are already blocked earlier by `require_active_subscription`).
Deliberately NOT a separate counter that increments per action and needs
a monthly reset job - there's no background scheduler in this app, and a
counter needing a reset is exactly the kind of thing that silently drifts
if that job is ever missed. Usage is instead just a live COUNT of
`QueryRecord`/`GeneratedArtifact` rows already created since the start of
the current calendar month - always correct by construction, and "this
month" resets itself for free the moment the calendar turns over.
Enforced as a 402 (a plan limit, not a permissions error, same convention
as every other cap in this app) in `routes_ask.py`'s `ask_stream` and in
`routes_artifacts.py`'s `create_report`/`create_presentation`/
`create_export` — the three artifact endpoints share ONE document cap,
not three separate ones, since they're structurally identical actions.
`GET /billing/status` now also reports `queries_used`/`query_limit`/
`documents_used`/`document_limit`, rendered on the Billing page as two
progress bars that turn amber at the cap. Verified end-to-end against a
real local SQLite DB (8 checks): a fresh Basic tenant reports the right
caps with zero usage, the 50th question is correctly NOT blocked but the
51st is (with a clear 402 message), the same shape for the 21st document
across all three artifact endpoints (rejected before even looking up the
underlying query record), `GET /billing/status` reports the real counts,
upgrading to Pro immediately raises the cap for the SAME existing usage,
and Premium stays genuinely unlimited even past 500 queries/documents on
record.

A platform-staff comp override (`PATCH /platform/tenants/{id}`,
`subscription_status: "active"`) now also accepts an optional `plan` -
defaults to Premium if omitted, specifically so a comped tenant never
falls into the *free* tier's 1-seat cap by accident (an unset plan on an
otherwise-active tenant would otherwise resolve to `seat_limit_for(None)
== 1`, the opposite of what a comp override is for). Staff can also
change an already-active tenant's plan directly from the Tenants page.

Verified end-to-end against the real app + real SQLite DB, including two
real bugs caught before they shipped: (1) the connection-cap check driven
against the real local seeded Postgres — 3 genuinely separate connections
created successfully on Basic, a 4th correctly blocked by the cap, not a
connectivity error, proving the check runs before any connector is even
constructed; (2) a comp override with no explicit plan correctly defaults
to Premium rather than silently capping the tenant at 1 seat. Also
verified: `GET /billing/plans`' pricing/limits are exactly right, subscribe
rejects both an unknown plan key and a valid-but-unconfigured one with
distinct, clear messages, and cancelling clears the plan.

**In-app notifications + subscription notices** (`app/db/models.py`'s
`Notification`, `app/api/routes_notifications.py`,
`app/user_notifications.py`, `frontend/components/NotificationBell.tsx`) —
a notification bell in the dashboard sidebar with an unread badge and a
dropdown of recent activity, polled every 60s. `Notification` rows are
per-user (read state is a personal fact), fanned out to a tenant's admins
using the same recipient list as the owner-activity emails, so the bell
and those emails always tell the same people. Events wired in so far:
**subscription activated** (also sends a confirmation email — the billing
flow previously sent nothing at all on a successful payment), **renews in
7 days**, **cancelled**, **renewal payment failed** (in-app + email), and
**a teammate accepted their invite**.

The "renews in 7 days" reminder needs a timer, and this app has no
in-process scheduler by design (same constraint as the uptime monitor and
audit-anchor checkpoints) — so it does what the monthly usage caps do:
compute on read. `GET /notifications` (the bell, polled while anyone on the
team has the app open) calls `maybe_send_expiry_reminder` for the caller's
tenant — a couple of date comparisons on each poll, a DB write + email
only the one time per period it actually fires. So reminders flow with
**zero configuration** for any team that logs in during the window.
`POST /notifications/reminders/run` runs the same per-tenant helper across
every active subscription, gated by a shared secret
(`SUBSCRIPTION_REMINDER_SECRET`, `503` until set); it's **optional**, for
guaranteed timing even for a team that doesn't open the app — driven by
the bundled GitHub Action (`.github/workflows/subscription-reminders.yml`,
just two repo secrets) or a Railway Cron Job
(`backend/scripts/subscription_reminders.py`). Both paths share the
once-per-renewal guard (`Tenant.expiry_reminder_sent_for`, which a renewal
advancing `subscription_expires_at` re-arms automatically), so they can't
double-send. Lead time is `SUBSCRIPTION_EXPIRY_REMINDER_DAYS` (default 7).
Setup (only if you want the cron) is in `docs/SUBSCRIPTION_REMINDERS.md`.
Verified end-to-end against a real SQLite DB (10 checks: activation drops a
notice, per-tenant isolation, mark-all-read, the sweep needs its secret,
one reminder inside the window and none outside it, a second sweep is a
no-op, a renewal re-arms it, a bare bell poll fires a due reminder on its
own without any cron, and a cross-tenant mark-read is a silent no-op).

**Free/Pro tiers & sub-accounts** — `Tenant.tier` (`app/db/models.py`) is
deliberately *derived*, not a stored column: `"pro"` means "currently has
an active subscription" and nothing else, so it can never drift out of
sync with `subscription_status` the way a second, independently-settable
field could. Two gates key off it:
- **Free plan is capped at 1 account.** `POST /auth/users` (adding a
  teammate) checks the calling tenant's tier and returns 402 once a free
  tenant already has one user — the admin who registered *is* that one
  account. Pro removes the cap entirely (no ceiling specified beyond "not
  1"). The Team page (`/team`) mirrors this client-side (disables "Add
  teammate" and shows a plan banner) purely for UX — the 402 from the
  backend is the actual enforcement, same pattern as every other
  plan-gated action in this app.
- **Free plan can't perform the core paid actions** — this was already
  true before tiers existed: `require_active_subscription`
  (`app/security/auth.py`) gates Ask, Risk scan, and creating a new data
  source connection behind `subscription_status == "active"`, i.e. Pro.
  Account/Team/Billing/Support/Audit screens are deliberately exempt, so a
  free-tier admin can still see their org's own state and upgrade.

The platform admin panel's **Tenants** page now shows, per tenant: its
tier badge, when it subscribed (`paid_at`), when the current period
renews/expires (`subscription_expires_at` — set on every successful charge
*including renewals*, unlike `paid_at` which only anchors the refund
window on the first one), and an expandable **sub-accounts** list — every
user under that tenant with their role and `created_at` ("when they opened
account"). A staff member setting `subscription_status` to `active` by
hand (a comp/support override, no real Paystack charge) gets the same
`paid_at`/`subscription_expires_at` treatment a real payment would, so a
comped tenant doesn't show up active-but-dateless.

Honest limitation on the expiry date specifically: it's a flat "+30 days
from the last successful charge" approximation, not read from Paystack's
actual billing-interval/next-charge data — same unverified-against-a-live-
account caveat as the rest of `app/billing/paystack.py`. A production
deployment with real recurring billing should read the real date off
Paystack's `subscription.create`/`invoice.*` webhook events instead.

No Alembic in this project — `app/db/session.py`'s `init_db()` runs a
small set of tracked `ADD COLUMN` statements after `create_all()` for
columns added to an existing model after its table might already exist on
some database (a dev machine, an already-deployed instance); each is
checked for existence first, so it's a safe no-op on a fresh database and
a real migration on an old one. Verified against a real pre-existing
SQLite DB with data already in it — columns added, existing rows
untouched. This is a stopgap for a two-model, no-Alembic project, not a
general migration system; a real schema-migration tool becomes worth it
the moment there's a second one of these.

Verified end-to-end (register → free tier blocks a 2nd account → platform
owner activates the tenant → tier flips to pro and both `paid_at`/
`subscription_expires_at` populate → pro allows a 2nd account → platform
expand view shows both sub-accounts with real timestamps → cancel drops
back to free and clears the expiry, without retroactively removing the
already-added 2nd account → a 3rd account is blocked again post-downgrade).

**Auth & multi-tenancy**
- Real registration/login: PBKDF2-SHA256 password hashing (600,000
  iterations, OWASP's current floor — raised from 260k in a security-review
  pass; the iteration count is stored in the hash string now, so it can be
  raised again without breaking anything, and a successful login on an
  old-format hash transparently re-hashes it), signed JWT sessions. Every
  route derives `tenant_id`/`user_id` from the verified token — never from
  the request body — so a client can't claim a wider scope than it was
  granted. Login also equalises response time on the "no such account"
  path (a fixed dummy hash is verified so it can't be told apart from
  "wrong password" by timing), and email is normalised (stored
  lower-cased, looked up case-insensitively so legacy mixed-case rows
  still resolve) so `Bob@x.com` and `bob@x.com` can't become two accounts.
  Verified: new hashes are `pbkdf2_sha256$600000$…` and verify; legacy
  2-part hashes still verify at 260k and upgrade on login; a mixed-case
  signup is stored lower-cased and logs in from any casing; a same-address
  re-registration in another case is a `400`; an unknown email is a plain
  `401`.
- Role-based access (`admin` can connect data sources and edit policy;
  other roles can't) and per-user capabilities (querying, report
  generation, email delivery, etc. can each be individually enabled).
- **Two-factor authentication** (TOTP, `app/api/routes_mfa.py`, `/security`)
  — scan a QR code with an authenticator app, then a 6-digit code joins
  the password at every login. Personal (any user can opt in) and
  org-wide (an admin can require it for everyone, present and future —
  anyone not yet enrolled is walked through setup the next time they log
  in, rather than being locked out). Secrets are encrypted at rest with
  the same backend that protects connected-database credentials
  (`app/security/secrets.py`). The real reason this needed backend
  changes, not just a frontend screen: `POST /auth/login` can't hand back
  a real session token before a required code is checked — a correct
  password alone would otherwise already be enough to reach every
  authenticated route — so it instead returns a short-lived "pre-auth"
  token, redeemable only at the two dedicated MFA endpoints, that
  `get_current_user` explicitly refuses to accept anywhere else. Code
  guessing is rate-limited the same way password guessing already is (a
  third `login_cooldown.py` guard, keyed by user id) — at the login-time
  checks (`/verify-login`, `/confirm-login`) and, since a security-review
  follow-up, at the **self-service** `/confirm` and `/disable` too. Those
  two verify a 6-digit code with a real session but had no throttle, so a
  stolen session token could have brute-forced the code (10⁶ space) to
  turn MFA off; they now share the same escalating-but-never-hard-locking
  cooldown as the login path (5 free attempts, then a doubling delay
  capped at 15 min, a correct code always clears it).
  Verified end-to-end against the real app (28 checks: enroll → confirm →
  disable, wrong-code rejection, the login-time code prompt AND the
  login-time enrollment path for a teammate who joined before the org
  policy existed, the pre-auth token's rejection by every normal
  endpoint, and the code-guessing cooldown) — and, live in a real browser
  against a real dev server, a genuine bug: React Strict Mode's
  deliberate double-invocation of effects called `/auth/mfa/setup` twice,
  and the QR code actually displayed on screen ended up for a secret the
  second call had already silently overwritten, so the confirm step it
  belonged to could never succeed — every code the user tried against the
  screen in front of them would fail. Fixed by ignoring the stale call's
  result rather than letting either response win the race arbitrarily,
  and reproduced fixed against the same live server before shipping.
  **Email recovery** for a lost authenticator device — reachable only
  from the login-time code prompt, i.e. only after a correct password
  (never a bare "enter your email" form, so it can't enumerate accounts
  or spam an address), it emails a longer-lived (15 min, not the shared
  5) recovery link to the account's own registered address; following it
  disables the lost authenticator so the next login re-enrolls a fresh
  one — self-service, rather than an admin removing and re-adding the
  account by hand. A security-REDUCING action, so the recovery page
  (`app/mfa-recovery/page.tsx`) deliberately requires an explicit confirm
  click rather than firing on page load, so an automated email link-
  scanner's prefetch can't silently disable someone's MFA. The tenant's
  other admin(s) are emailed about it immediately either way (see
  "Owner-activity email notifications" below) — a lost-device recovery
  triggered by someone else is exactly the kind of event an owner needs
  to see right away. Verified end-to-end against a real local SQLite DB
  (8 checks: recovery only reachable via a correct-password pre-auth
  token, a garbage token rejected, redeeming disables MFA and notifies
  the OTHER admin but never the recovering user themselves, a wrong-
  purpose token rejected, login correctly re-opens fully when MFA was
  self-enrolled vs. correctly re-demanding a fresh SETUP when the org
  policy requires MFA) and a real local browser session confirming the
  page does NOT redeem on load, only on the explicit confirm click. NOT
  built: backup/recovery codes as an alternative to the email path.
- **Idle sign-out**: independent of the session token's own (much longer)
  expiry, 10 minutes with no mouse/keyboard/scroll activity shows an "Are
  you still here?" prompt; one more minute unanswered signs out and
  requires signing back in (`components/InactivityWatcher.tsx`, mounted
  in `AuthGate` for the tenant app only — not `/platform`, which has its
  own separate session entirely). Deliberately no fixed absolute session
  cap — activity alone keeps a session usable, only inactivity ever ends
  one early.
- **Per-tenant subdomains** (`app/tenant_slug.py`, `wamco.
  getmeridiananalytics.com`) — auto-assigned from the company name at
  registration (`generate_unique_subdomain`, collision-resolved: a second
  "Wamco Inc" gets `wamco-inc2`, not a silent clash), and a genuine login
  boundary, not decoration: `POST /auth/login` accepts an optional
  `subdomain`, and when the caller sends one, the account must belong to
  the tenant that subdomain actually resolves to — a fully correct
  password for the wrong tenant's subdomain is refused with the same
  generic message a nonexistent subdomain gets, so neither response leaks
  which case actually happened. The generic domain's login is completely
  unaffected — unrestricted, exactly as before this existed — since the
  boundary only ever activates when a subdomain is actually sent. One
  wildcard Railway custom domain (`*.getmeridiananalytics.com`) covers
  every tenant's subdomain at once — see `docs/RAILWAY_DEPLOY.md` §9 — so
  this doesn't consume a custom-domain slot per tenant. Existing tenants
  from before this feature shipped are backfilled automatically on boot
  (`_backfill_tenant_subdomains()` in `app/db/session.py`), and
  `/platform/tenants` lets staff view or rename any tenant's subdomain by
  hand. Verified end-to-end against the real app (24 checks): the login
  boundary in both directions (tenant A's correct password refused on
  tenant B's subdomain, and vice versa), the generic domain staying fully
  unrestricted, collision-resolved auto-generation, staff rename/reject-
  invalid/reject-reserved/reject-clash, and the backfill path for a
  pre-existing tenant — which caught a real bug before it shipped: the
  backfill loop's uniqueness check queried the database without flushing
  first, so two same-named tenants in the same batch (a real case:
  leftover same-named local test tenants) could both compute the
  identical "unique" subdomain and collide for real at commit. Fixed with
  a flush after each assignment.
- **Cross-subdomain session handoff** (`POST /auth/handoff/create` +
  `POST /auth/handoff/redeem` in `app/api/routes_auth.py`, landing page at
  `frontend/app/auth/handoff/page.tsx`) — a login or registration that
  happens on the generic domain now visibly lands the user on their OWN
  tenant subdomain (the address bar actually changes), rather than
  leaving them on `www` forever with the subdomain only reachable by
  typing it in manually. `sessionStorage` is deliberately per-origin (a
  real security property — one tenant's session must never be readable
  from another's subdomain, the "mall vs. individual store" boundary the
  per-tenant-subdomain login check above already enforces), so a plain
  redirect can't carry a session across origins — a genuine hand-off is
  required. Built by reusing the existing short-lived (5-minute) pre-auth
  JWT machinery from the MFA login flow (`create_pre_auth_token` /
  `decode_pre_auth_token` in `app/security/auth.py`) with a new
  `purpose="handoff"`: minted at the exact moment of redirect (not
  earlier, so its window is never eaten by however long MFA entry took),
  carried in the URL **fragment** (`#token=...`, never sent to any
  server, unlike a query string — deliberately NOT the discredited OAuth
  "implicit flow" pattern of putting the real long-lived `access_token`
  itself in a URL), and redeemed at `/auth/handoff` for a genuinely fresh
  `access_token` — the handoff token itself never carries real session
  material, and `get_current_user` already rejects any `pre_auth` token
  outright regardless of purpose. Deliberately NOT single-use/replay-
  tracked, relying on the short TTL alone — the same trade-off the
  existing MFA pre-auth tokens already make. If the handoff can't be
  minted for any reason (network blip, no subdomain assigned yet), the
  frontend falls back to the session already saved locally on the generic
  domain rather than leaving the user stuck. Verified end-to-end against
  a real local SQLite DB: register → mint handoff token → redeem with NO
  Authorization header at all (the whole point) → fresh access_token
  authenticates a real request → a garbage token is rejected → an MFA
  pre-auth token (`purpose="mfa_login"`) is correctly refused when
  presented as a handoff token, confirming purpose isolation holds in
  both directions.
- **Real invite-by-email** (`app/invites.py`, a shared `Invite` table and
  helpers used by both a tenant's team and Meridian's own internal
  platform staff) — replaces the old pattern of an admin picking a
  temporary password for someone else. An admin/owner names an email +
  role; the recipient gets a real email with a link and must accept it
  themselves within 24 hours (proving control of that inbox, choosing
  their own password) or the invite is automatically treated as expired
  — and can be revoked outright before that from the Team page
  (`POST /auth/team/invite/*`) or the platform Staff page
  (`POST /platform/staff/invite/*`). No background scheduler exists in
  this app, so expiry is enforced lazily — checked (and flipped to
  `status="expired"`) wherever an invite is read, not by a cron sweeping
  the table. The token itself is never stored in plaintext (only its
  SHA-256 hash, same reasoning as password hashing) and is carried in a
  normal query-param link (`/accept-invite?token=...` — a tenant's own
  link already points at that tenant's subdomain when one exists, see
  `_team_accept_url`), unlike the session-handoff token above: an invite
  token is inherently already exposed via the email transport itself, so
  the extra fragment-vs-query distinction that matters for a real
  `access_token` doesn't apply here. Seat-limit checks count pending
  invites alongside real accounts, so a stack of unaccepted invites can't
  blow past a plan's cap the moment they're all accepted at once.
  Re-inviting the same address replaces any still-pending invite for it
  rather than piling up duplicates. Verified end-to-end against a real
  local SQLite DB and a real local browser flow: invite sent → accept
  page shows the real org/role/inviter → accepting creates the account
  and logs the acceptor straight in → re-accepting a consumed token is
  rejected → a revoked invite is rejected at accept time → a stale
  pending invite lazily expires the moment anything reads it — for both
  the tenant-team and platform-staff flows.
- **Owner-activity email notifications** (`app/agents/notifications.py`)
  — critical account activity now reaches the relevant "account owner"
  by email, not just the in-app audit log, which only ever gets checked
  by someone who thinks to look. A tenant's admin(s) are emailed when
  anyone else on their team signs in, when a teammate is invited, and
  when an invite is accepted; Meridian's own platform owner(s) get the
  same three for platform staff. Always excludes whoever just performed
  the action from its own notification (an admin isn't emailed about
  their own sign-in) — the point is visibility into what OTHERS did, not
  a self-notification loop. Best-effort throughout, same as every other
  system email here: a failed send is logged and swallowed, never
  allowed to fail the request that triggered it. Verified end-to-end
  alongside the invite flow above, including confirming a solo admin's
  own sign-in produces zero emails.
- **Welcome email on registration**, from the founder (`Joel Umunnah`) —
  sent best-effort right after a new tenant's first admin account is
  created, briefly explaining what Meridian does and nudging them to
  connect a data source or upload a document. Verified as part of the
  same end-to-end test above.
- Session-signing and credential-encryption now use independently
  rotatable secrets (`JWT_SECRET_KEY` vs `APP_SECRET_KEY`, falling back to
  a shared key if unset, for backward compatibility) — rotating one no
  longer forces rotating the other. Credential encryption itself can run
  in two modes: a static local key (default) or real envelope encryption
  via AWS KMS for production — see `app/security/secrets.py` and
  `docs/CLOUD_KMS.md`. Verified against a stubbed KMS client (exact API
  calls, full encrypt/decrypt round trip, confirms the plaintext
  credential never appears in the stored token), not a live AWS account —
  none available here.
- **Production config is now enforced at startup, not just documented**
  (a security-review fix, `validate_startup_config` in `app/config.py`,
  called from the startup event). The backward-compatible fallbacks above
  are a real footgun: with only `APP_SECRET_KEY` set, that one value signs
  tenant sessions, signs platform-owner tokens, *and* is the local-KMS
  credential-encryption key — one leak is a total compromise. So when
  `ENVIRONMENT=production` (or `KMS_PROVIDER=aws`, which nobody runs
  outside production), the process **refuses to start** unless
  `JWT_SECRET_KEY` and `PLATFORM_JWT_SECRET` are both set and distinct
  from `APP_SECRET_KEY` and each other, and `KMS_PROVIDER=aws` with
  `AWS_KMS_KEY_ID` set. A SQLite `METADATA_DB_URL` or a localhost
  `FRONTEND_ORIGIN` in that mode logs a loud warning but doesn't block.
  Development (the default) is completely unaffected. Verified: dev mode
  bypasses every check; production with collapsed secrets raises listing
  each problem; `jwt == app` and `platform == jwt` are each caught;
  `KMS_PROVIDER=aws` with no key id is caught; a correct hardened config
  passes with only the soft warnings; and the real app still boots and
  serves `/health` in dev.

**Connectors**
- **SSRF guard on the connection host** (`app/security/ssrf.py`, a
  security-review fix). A connection's `host` is set by a tenant admin and
  then dialed *from the backend's own network* — without a guard, an
  authenticated paying admin could point a connection at `127.0.0.1`,
  `169.254.169.254`, or an internal `10.x` address and use Meridian as a
  working internal port scanner (and, against an internal DB with weak
  auth, an actual read path). `check_connection_host` now resolves the
  host and refuses anything that lands on a private / loopback /
  link-local / CGNAT / cloud-metadata address (and fails closed on an
  unresolvable name). Checked both when a connection is created *and* when
  a connector is built to run a query — the second check narrows the
  DNS-rebinding window. A self-hosted deployment that legitimately needs a
  private-network database sets `ALLOW_PRIVATE_CONNECTION_HOSTS=true`.
  Verified: every private/loopback/link-local/CGNAT/metadata/IPv6-ULA
  address and `localhost` are blocked; public IPs pass; an unresolvable
  host is blocked; the opt-out flag disables it; `POST /connections` with
  an internal host is a `400` + an audited `connection_host_blocked`; a
  public host passes the guard and only then fails at the connectivity
  check (so it isn't over-blocking).
- **PostgreSQL** and **MySQL/MariaDB**, both proven against real instances:
  every query runs inside an explicit read-only transaction
  (`BEGIN TRANSACTION READ ONLY` / `START TRANSACTION READ ONLY`), on top of
  a recommended SELECT-only database role. `verify_read_only()` proactively
  proves this by attempting a real write and requiring the database to
  reject it — connecting a writable credential is refused before it's ever
  saved.
- **SQL Server** connector is implemented (`app/connectors/mssql.py`) but,
  unlike Postgres/MySQL, **not proven against a real instance** — no test
  instance available in this environment. It's also structurally weaker:
  T-SQL has no session-level read-only transaction mode equivalent to
  `BEGIN TRANSACTION READ ONLY`, so `verify_read_only()` there proves only
  that the connecting role's own GRANTs reject a write, not that the
  session itself is incapable of one. See the docstring in that file.
  (Caught in a later pass: `app/agents/planner.py` kept its own separate
  connector registry that hadn't been updated when MSSQL was added to
  `routes_connections.py` — a saved MSSQL connection would work at
  creation time but fail every time someone actually asked a question
  against it. Fixed; both registries now agree, and `build_connector` is
  exported from `planner.py` so the risk scan reuses the same one.)
- **Snowflake** connector (`app/connectors/snowflake.py`) — same
  interface, same shape, but honestly weaker on the one thing the other
  three lean on hardest: Snowflake has no session-level read-only
  transaction mode at all (no `BEGIN TRANSACTION READ ONLY` equivalent),
  so `verify_read_only()` there is a real attempted write (`CREATE
  TEMPORARY TABLE`, genuinely rejected or not by the server) with no
  independent backstop the way Postgres/MySQL have one — its correctness
  is only as strong as the connected role's own grants, stated plainly in
  the connector's own docstring rather than presented as equivalent.
  Snowflake's connection model also doesn't fit the existing host:port:
  database shape at all — it needs a *warehouse* (compute) and optionally
  a *role*, neither of which any other connector needed a place for. Gave
  `DataSourceConnection` a new `extra_config` JSON column for exactly this
  (connector-specific parameters that don't generalize) rather than
  bolting warehouse/role onto columns that don't mean that for anyone
  else. Unverified against a live Snowflake account (none available here)
  — built strictly to snowflake-sqlalchemy's documented contract, same
  category of caveat as Paystack; verified everything that *can* be
  proven without one: the connector's own validation (rejects a missing
  warehouse before ever attempting a connection), that it builds a
  correct SQLAlchemy engine/URL, and a real Postgres regression check
  (still connects and verifies read-only against the real local seeded
  database) confirming the new shared `extra_config` parameter didn't
  disturb the three connectors that don't use it.

  Caught and fixed two real bugs while adding this, both before either
  ever reached production: (1) `cryptography` needed bumping
  (`43.0.1` → `50.0.1`) to satisfy Snowflake's driver — reverified the
  app's own Fernet credential encryption still round-trips correctly
  under the new version rather than assuming it. (2) The light-migration
  path (`app/db/session.py`, see the Free/Pro tier section above for why
  it exists) added `extra_config` as plain `TEXT` — which silently
  accepts a JSON write but returns a raw string instead of a parsed dict
  on read, because SQLAlchemy's `JSON` type on Postgres only applies its
  read-side deserialization when the underlying column is genuinely
  Postgres's native `json` type. Caught by actually writing a dict
  through a migrated column and reading it back against real Postgres,
  not by reasoning about it — the migration is dialect-aware now
  (`json` on Postgres/MySQL, `TEXT` on SQLite, matching what
  `create_all` would produce natively on each).
- Connector interface (`app/connectors/base.py`) is small enough that
  adding Oracle/BigQuery/Databricks/etc. means implementing 4 methods,
  not a redesign — not built in this slice, since I can't test them
  without real instances.

**The analysis pipeline** (`app/agents/planner.py`)
- Schema discovery filtered to each tenant's table/column policy before it
  ever reaches the LLM.
- SQL generation (Claude) -> validated (single `SELECT`, no DDL/DML, no
  stacked statements, no comment smuggling) -> executed -> output-checked
  (sensitive-column blocklist, raw-row ceiling) -> row-level policy checked.
- Deterministic data quality (completeness, duplicates, outliers) and
  analytics (sums, growth rates, grouping) — the LLM never does arithmetic,
  it only interprets numbers already computed.
- **Anomaly detection**: z-score on period-over-period growth rate across
  groups, plus a missing-data check — deterministic, no LLM.
- **Investigation agent**: automatically cascades the top anomaly through
  further available dimensions (product/branch/category/state/...) — the
  top contributor at each level becomes the filter for the next, so a
  "revenue declined in South-East" anomaly can drill South-East -> its top
  product -> that product's top branch, bounded to 3 levels
  (`MAX_CASCADE_DEPTH`) and stopping early once it runs out of unused
  dimensions. Reuses the same generate-validate-execute path as any other
  query at every level — not a less-checked shortcut.
- **Conversational follow-ups**: a `Conversation` row carries structural
  context (table, dimensions, top groups — never raw rows) between
  questions, so "what about Kano?" resolves against the prior analysis.
- Insight explanation (Claude) — what/where/when/contributors/confidence/
  next-question, using only the numbers it was given.
- **Error messages to the client are generic** (security-review
  follow-up). `/ask/stream` and `/scan/stream` used to stream
  `str(exception)` straight to the browser on an unexpected failure — a
  SQLAlchemy or connector error string routinely carries the failing
  query and sometimes connection detail. The unexpected-error path now
  logs the real exception (with a stack trace) server-side and streams a
  generic "failed unexpectedly, try again" step; the insight step's
  fallback message is generic too (its real reason was already going to
  the audit log, not just the response). App-authored messages that are
  safe to show — a policy violation naming a scope column, a rate-limit
  retry time, an "unsupported document type" — are unchanged.

**Forecasting** (`app/agents/forecasting.py`) — the "predictive" half of
descriptive/diagnostic/predictive/prescriptive (section 15); only the first
two existed before. Deterministic, no LLM, same principle as
anomaly_detection.py: ordinary least squares on the already-computed period
totals for the current question's top groups, projected a few periods
forward. Be clear about what this is NOT — no seasonality model, no
statistically-derived confidence interval, and it assumes the recent trend
continues, which is routinely wrong for real business data. Every surface
says "if the recent trend continues", not "prediction" unqualified, and the
frontend renders it with dashed/outlined bars, visually distinct from the
solid "By group" bars showing what actually happened. "Prescriptive"
(what to DO about a projection) is deliberately not attempted — that needs
judgment a deterministic agent can't responsibly exercise, and letting an
LLM narrate a recommendation risks the exact failure mode
`insight_agent.py`'s docstring already warns against, so `insight_agent.py`
was left untouched entirely; the forecast is shown as its own deterministic
panel, never routed through the LLM. Verified against the real module (not
a reimplementation) with actual pandas/numpy: a clean synthetic uptrend
recovers the exact expected slope and projected values, a downtrend and a
flat series classify correctly, too few periods correctly returns nothing,
and the top-N-groups bound is respected.

**Document intelligence** (`app/agents/document_intelligence.py`,
`/documents`) — upload a PDF, DOCX, PPTX, or XLSX; text (and table cell
content, and — for PPTX — speaker notes, labelled `[Speaker notes]` so
it's clear in the extracted text which content was on-slide vs. narration-
only) is extracted once at upload time and can be attached to a question on Ask,
where it's referenced alongside the database analysis — **or a document can
BE the data source in its own right**: pick it in the same "Data source"
dropdown a database connection would go in (`app/page.tsx`), no database
connection involved at all. `POST /ask/stream`'s `connection_id` is
optional now (rejects a request with neither it nor `document_ids` set);
`planner.py`'s document-only branch skips schema discovery/SQL generation/
anomaly detection/forecasting entirely — none of those apply without a
query result — and calls a dedicated `explain_document_only()` prompt
(`insight_agent.py`) tuned for direct document Q&A rather than overloading
the metrics-explanation prompt with an "unless there's no database" branch.
Same subscription gating as the database path (still a core paid action),
same rate/concurrency limits, same prompt-injection defence. `QueryRecord`
needed no schema change for this — `connection_id` there is a plain string
with no FK constraint, so a document-only analysis is recorded under a
`"document-only"` sentinel rather than a real connection id, verified safe
by reading every place that column is read (history list/detail, report/
presentation generation) before choosing that over a migration. This is
the first genuinely externally-authored content anywhere in this app's LLM calls —
schema field names and row values come from a database the tenant already
connected and authorized, but a document could contain anything, including
text written to look like instructions. Handled with the same discipline:
extracted text is always passed to the LLM as a labelled, untrusted
`reference_documents` payload (see `insight_agent.py`), never blended into
instruction text, and the model is explicitly told not to comply with
anything inside it that looks like an instruction. Attaching a document
also opts a question out of the result cache (see Query result cache above)
and out of follow-up chaining, rather than trying to fold document identity
into either of those correctly. Scanned/image-only PDF pages are read via
OCR (Tesseract, via PyMuPDF for rendering + pytesseract — see
[docs/OCR.md](docs/OCR.md)): per-page, not per-document, so a mixed PDF
(some real-text pages, some scanned, e.g. a native report with a scanned
signature page appended) gets native extraction for the pages that have it
and OCR only for the pages that need it. Bounded to 15 OCR'd pages per
document (OCR is genuinely CPU-expensive, unlike the near-instant native
path, and uploads are still synchronous). Fails open, not closed, if
Tesseract isn't installed at all — falls back to the pre-OCR empty-page
behavior rather than crashing the upload, same pattern as Redis and the
Anthropic client elsewhere in this app. `ocr_pages_used` is surfaced on
every document (upload/list/get responses, and as a "(N scanned page(s)
read via OCR)" note on the Documents page) so OCR'd text — real but
lower-confidence than a native text layer — is never presented identically
to a clean extraction. NOT built: real PDF table structure (flattened to
reading-order text, OCR'd or native). Bounded to 20MB per upload, 50,000
extracted characters, and (a security-review pass) `MAX_DOCUMENTS_PER_TENANT`
stored documents at once — deleting one frees a slot; an oversized upload
is now rejected from its declared size before the body is read into
memory, not only after.
Extraction verified against real generated PDF/DOCX/PPTX/XLSX files (not
reimplemented logic) — actual page text, paragraphs, tables, multi-sheet/
multi-slide content, PPTX speaker notes, truncation at the character cap,
and graceful (non-crashing) handling of a corrupt file all confirmed. The whole feature was then
verified with a real HTTP round trip through the live FastAPI app against
a real SQLite database (register → upload → list → get → permission-denied
delete by a non-uploader → admin delete), and separately, cross-tenant
document access was confirmed blocked both at the API layer (404) and at
the exact DB query `planner.py` uses to resolve `document_ids` — the one
place a wrong tenant filter here would have mattered.

OCR verified with a real local Tesseract install (direct-download installer,
same pattern used for Postgres earlier in this project — not mocked): a
genuinely image-only PDF page (confirmed empty under `pypdf.extract_text()`
*before* testing OCR, to prove the fallback path was actually exercised
rather than trivially passing) correctly OCR'd; a mixed document (one real-
text page, one scanned page) correctly used native extraction for one and
OCR for exactly the other; and the full upload → get → list round trip
correctly surfaced `ocr_pages_used` throughout.

**Real embedded pictures, described by AI vision** (`app/agents/
document_intelligence.py`) — phase 2 of the analysis-engine work the same
user asked for after seeing the structured-spreadsheet fixes above: "if
it's a PDF, read every word, table, text, format, pictures... same for
PPTX." Text and tables were already covered; a real embedded photo,
chart-as-image, or diagram had no text form at all before this, so it was
completely invisible to any analysis regardless of how good the text
extraction got. `_describe_images()` is a small, deliberately narrow
exception to this module's "extraction, not comprehension" rule (see its
docstring) — there's no way to "extract" a picture as text without
actually looking at it, so a batched vision call (every image in one
request, not one call per image — far cheaper and faster) describes what
each one factually shows, explicitly told never to invent a number or
word it can't actually read in the image, the same anti-hallucination
discipline this app applies everywhere else. Descriptions are folded into
the same `extracted_text` every other extraction already produces,
clearly labelled (`[Image on page 3]: ...` / `[Image on slide 5]: ...`)
so it's obvious in the text which parts are native content vs. an AI's
read of a picture — same spirit as how OCR'd text is already labelled
apart from a native text layer.

Bounded and defensive throughout: capped at 20 images per document (a
heavily-illustrated deck doesn't turn into 40 vision calls' worth of
latency and cost); an image under roughly 80×80px is skipped as almost
certainly a decorative icon/bullet/logo rather than real content; each
image is downsized to fit within 1024px before sending (keeps the
request small without losing the kind of detail a factual description
actually needs); embedded images sharing the same underlying picture (a
logo reused on every page of a PDF) are deduplicated so the same picture
isn't billed and described once per page it appears on. Fails open at
every stage, matching the same discipline Tesseract's optional OCR
dependency already established: no Anthropic key configured, the vision
call itself failing, or the model returning something that isn't a clean
JSON array all degrade to "no descriptions," never a failed or degraded-
looking upload. A new `images_described` count is surfaced everywhere
`ocr_pages_used` already is (upload response, list, detail, the Documents
page's file line, the audit log) — real, but a different kind of "real"
than a native text extraction, worth flagging the same way OCR'd text
already is rather than presenting identically to a clean extraction.

Verified with real files and a mocked vision call (this dev environment
has no live Anthropic key — the same constraint every LLM-touching test
in this codebase works around): a real PDF built with `pymupdf`,
containing one genuine embedded picture, correctly extracted, described,
and labelled with its real page number; a 20×20 test image correctly
filtered out by the minimum-dimension check; a real PPTX built with
`python-pptx` with a real embedded picture, same result labelled by slide
number; the vision call raising an exception, and the model returning
non-JSON prose, both confirmed to degrade to zero descriptions without
crashing the extraction; a plain text-only PDF confirmed to never even
attempt a vision call (nothing to describe, no wasted request); and the
full real HTTP round trip (register → upload a real PDF with a real
embedded image → list → get) confirming `images_described` and the
actual description text reach every layer correctly.

**...and the same for XLSX** — a real, direct follow-up question ("how
about excel format?") right after the PDF/PPTX version shipped. XLSX can
embed real pictures too (a chart pasted in as an image, a logo, a photo),
and the extraction is possible - but a real, checked constraint shaped
how: `extract_xlsx()`'s existing text extraction reads a sheet in
openpyxl's `read_only=True` streaming mode specifically to handle a wide
or heavily-populated sheet without loading it entirely into memory (the
same mode this document analysis project's spreadsheet work has cared
about since the 5,232-column workbook earlier in this README) - and a
`ReadOnlyWorksheet` in that mode simply doesn't expose embedded images at
all (confirmed directly: it lacks the attribute entirely, not just an
empty result). Reaching them needs a genuinely separate, second,
normal-mode `load_workbook()` call - a real cost that mode was chosen to
avoid for cell data specifically. Judged acceptable here because by the
time this runs, the file has already passed the 20MB upload cap and the
zip-bomb ratio check (see "Locked and unsafe file detection" below) - the
unbounded-blow-up risk read-only mode also happens to guard against is
already ruled out by those; what's left is just ordinary parse time for
an already size-capped file. Images are labelled by sheet name and
anchor cell (`[Image in sheet 'Report', near C5]: ...`), reusing the same
`_describe_images()` batched vision call and every one of its existing
bounds (20 images/document, 80px minimum dimension, 1024px resize)
unchanged.

Testing this against the real file surfaced one more real gap, fixed
consistently across all three formats, not just XLSX: `extract_xlsx()`'s
call to the image-description code had no enclosing `try/except` of its
own — only the smaller operations *inside* it did. A test that patched
the image-extraction call to simply raise (simulating an unexpected
failure the inner handling didn't anticipate) crashed the *entire*
extraction, discarding cell text that had already been read out
successfully. Once caught, the same audit found the identical gap in
`extract_pdf()` and `extract_pptx()` — both already had per-image
try/excepts inside their extraction loops, but the outer
`_describe_images()` call itself sat outside any try/except at that
level. All three now wrap that whole block, so an image-side failure of
any kind costs a document its image descriptions only, never the text
that was already successfully extracted alongside them — confirmed by
patching `_describe_images` to raise directly against all three formats
and checking the real text still comes through afterward.

Verified with a real XLSX built with openpyxl containing a genuine
embedded picture (extracted, described, and correctly labelled by sheet
and cell, alongside real cell values extracted normally); a 30×30 test
image correctly filtered by the minimum-dimension check; the new
outer-safety-net fix confirmed on all three formats (PDF/PPTX/XLSX) by
directly forcing `_describe_images` to raise and checking the
already-extracted real text survives untouched; and a full real HTTP
round trip (register → upload a real XLSX with a real embedded image →
get) confirming `images_described` and the real description text reach
the API correctly alongside the real cell data.

**Locked and unsafe file detection** (`app/agents/document_intelligence.py`,
`routes_documents.py`) — before this, a password-protected file just
failed extraction with a generic, confusing error (or, for some
malformed cases, silently extracted as empty) — nothing told the user
the actual, simple fix ("remove the password and re-upload"). Now
checked explicitly, before any real parsing is attempted:
- **PDF**: `pypdf`'s own `reader.is_encrypted` flag, with one real
  nuance handled correctly — a PDF can be "encrypted" only to restrict
  printing/editing via an owner password, with a genuinely blank user
  password, which makes it completely readable without ever prompting
  anyone. A blank-password decrypt is tried first; only a PDF that's
  still locked after that is rejected as needing a real password.
- **DOCX/XLSX/PPTX**: these are plain ZIP archives when unprotected: a
  password-protected one is instead wrapped in the much older OLE2/
  Compound File Binary Format container (the same one legacy
  `.doc`/`.xls`/`.ppt` used) — recognizable from its first 8 bytes alone,
  before ever attempting to unzip it. Same signature-based detection
  `msoffcrypto-tool` and similar libraries use; no new dependency needed
  to *detect* it (this app never attempts to decrypt one — a locked file
  is always rejected with instructions to unlock and re-upload, never
  guessed at or cracked).

Also checked, and genuinely a safety concern rather than just a UX one:
DOCX/XLSX/PPTX's zip-archive structure means a maliciously crafted file
could declare a small compressed size but an enormous uncompressed one (a
"zip bomb"), aimed at exhausting memory/CPU the moment
openpyxl/python-docx/python-pptx actually decompresses it. Every entry's
*declared* compressed/uncompressed size (metadata every zip carries,
readable without decompressing anything) is checked against a maximum
compression ratio and a total-uncompressed-size cap before any real
parsing starts.

A locked or unsafe file now gets a specific 422 with a plain-language
explanation instead of a generic 400, and is audited as `document_upload_
locked`/`document_upload_unsafe` (status `"denied"`, not `"error"` — this
isn't the app failing at anything, it's an expected, correctly-handled
outcome). Verified against real files, not mocked: a genuinely encrypted
PDF built with `pypdf.PdfWriter.encrypt()` (real user password) correctly
rejected; the exact same encryption with a *blank* user password (owner-
password-only) correctly stays readable; a file starting with the real
OLE2 signature bytes correctly detected as a locked XLSX; a real ZIP
archive containing a 50,000,000-byte run of zeros compressed down to
under 50KB (the actual shape of a zip bomb, without needing gigabytes of
real disk space to construct one for the test) correctly rejected as
unsafe; and a perfectly ordinary XLSX confirmed to extract completely
unaffected by any of the above. Also confirmed through a real HTTP round
trip against the live FastAPI app (register → upload a real encrypted
PDF → real `422` with the real message).

These are all *structural* checks - they read a file's own declared
metadata, they don't scan its contents for known malware. An optional
signature scan on top is available: set `MALWARE_SCAN_PROVIDER=clamav` and
`app/security/malware_scan.py` runs every upload's raw bytes through a
ClamAV daemon (`clamd`) over its INSTREAM protocol - a stdlib socket, no
vendor client library, the same "no SDK" approach as the SMTP backend -
before anything parses the file. A flagged file is rejected with `422` and
audited as `document_upload_malware`. Off by default (`"off"` - no extra
infrastructure, the structural checks still run); when on, a `clamd`
outage refuses uploads (`503`, `document_upload_scan_unavailable`) rather
than passing them unscanned, unless `MALWARE_SCAN_FAIL_OPEN=true`.
Verified with a stub `clamd` speaking the real INSTREAM framing
(`tests/verify_malware_scan.py`): the wire protocol for a clean stream and
a `FOUND` verdict, an unreachable daemon surfacing as an error not a
crash, and the upload route returning `200` / `422` / `503` for
clean / flagged / unavailable. Setup in `docs/MALWARE_SCANNING.md`.

**Clean, single-pass insight text** (`app/agents/insight_agent.py`,
`app/agents/query_generator.py`) — the model is now explicitly instructed
to never show its own reasoning process (arithmetic, reconsidering an
answer) in any field it returns; caught live against the real, funded
Anthropic API, not theorized about: an early production test asked a
genuine question against an uploaded spreadsheet and got back a
technically-correct answer whose "what" field visibly included the
model's own mid-sentence correction ("West had the highest revenue at
120000... wait, let me recompute..."). Every prompt that can involve any
arithmetic or judgment call (the insight explanation, the document-only
explanation, and the SQL-generation rationale) now explicitly says to do
that thinking privately and output only the finished conclusion.

**"Made by Meridian" branding on every generated download**
(`app/agents/report_generator.py`, `presentation_generator.py`,
`export.py`) — every artifact a user downloads now visibly credits the
platform, proportionate to what each format actually supports:
- **PDF report**: a `MeridianPDF(FPDF)` subclass overrides fpdf2's
  `footer()` hook, which fires automatically on every page (including
  ones added by `auto_page_break`) — a thin rule, "Made by Meridian -
  getmeridiananalytics.com", and a page number, on every page of a
  multi-page report, not just the first.
- **PPTX presentation**: python-pptx has no equivalent per-slide
  callback, so a small bottom-right textbox is added explicitly after
  each of the three slide-builder helpers — verified on all 5 slides of
  a real generated deck, not just the title slide.
- **CSV export**: deliberately carries NO in-data branding — CSV is pure
  tabular data with no metadata capability, and a downstream script
  piping the export into another tool expects exactly the columns it
  asked for. Injecting a branding row/comment would silently corrupt
  that. Branding here is filename-only (`meridian-export-*.csv`), never
  touching a single byte of the actual data.
- **XLSX export**: real metadata support, so it gets a fuller (but still
  non-intrusive) treatment via `pd.ExcelWriter`'s underlying openpyxl
  workbook — document properties (`creator`/`last_modified_by`/
  `description`) and a print-only footer (`ws.oddFooter`, visible only
  when printed/exported to PDF, invisible to any cell read) — neither of
  which touch the actual data rows, verified by reading the file back
  with both `pandas` and `openpyxl` and confirming the values are
  byte-for-byte what went in.

Verified end-to-end against the real HTTP pipeline (register → mark
tenant active → generate a real report/presentation/export from a real
`QueryRecord` → download each file back and inspect it): PDF footer text
extracted and confirmed present, PPTX branding confirmed present on
every one of 5 slides, CSV confirmed byte-identical to its unbranded data
(only the filename differs), and XLSX confirmed to carry the metadata
and print footer while its actual cell values remain untouched.

**A real visual design, not just a footer line** (`app/agents/
report_generator.py`, `presentation_generator.py`, `export.py`,
`app/assets/meridian_mark.png`) — the branding above was a name on the
page; the PDF and PPTX underneath it were still fpdf2/python-pptx's plain
defaults (the deck in particular used PowerPoint's stock "Office" theme
with no Meridian color anywhere on it at all). Now both use the exact same
palette as the web app (`frontend/app/globals.css`) and the branded
emails:
- **PDF report**: every page gets a teal-deep header band with the logo
  mark and "MERIDIAN" wordmark (fpdf2's `header()` hook, the same
  automatic-on-every-page guarantee `footer()` already relied on for its
  own branding). Section headings are teal-deep with a short colored rule
  underneath instead of relying on bold weight alone to separate them —
  the same visual role `ResultView.tsx`'s `border-t border-line` dividers
  play on screen. The Confidence line is color-coded by level (teal-deep/
  amber/ink-soft), matching the web app's own `ConfidenceBadge`. The
  Breakdown table gets a teal-deep header row and alternating light-row
  banding instead of a plain bordered grid.
- **PPTX presentation**: the title slide gets the full treatment — a
  solid teal-deep background, the logo mark, white/paper title text — a
  real cover slide. Every other slide stays on a white background (a
  table or several paragraphs of analysis needs the readability a light
  background gives it far more than it needs to look like the cover) but
  gets a teal-deep title with a teal accent bar underneath, matching the
  PDF's section-heading treatment. The table slide's header row is
  teal-deep with bold white text and alternating row banding, same as the
  PDF's. Every run explicitly sets `font.name = "Arial"` — the closest
  cross-platform equivalent to the web app's Helvetica/system-ui stack —
  rather than inheriting whatever font PowerPoint's default theme
  supplies, which was never a Meridian brand choice at all.
- **XLSX export**: the header row is now bold white-on-teal-deep, the
  header row is frozen (`ws.freeze_panes`), and column widths are sized
  to their content (capped, so one long free-text outlier can't blow out
  the whole sheet) — on top of the document properties and print footer
  already there. All formatting-only: no cell VALUE is touched, the same
  invariant the print footer and CSV's filename-only branding already
  relied on.
- **CSV stays exactly as it was** — deliberately: it has no metadata or
  styling capability at all, and the existing filename-only branding
  decision (never touching a byte of the actual data, since a downstream
  script's `pd.read_csv()` expects exactly the columns it asked for)
  already covers it correctly.

The logo mark (`app/assets/meridian_mark.png`) is a small, genuinely
generated asset — the same simple design as the browser favicon
(`frontend/app/icon.svg`): a teal-deep rounded square with a bold white
"M", rendered once via Pillow and checked into the repo, not regenerated
per-report.

Verified two ways, since this environment has no way to open a PDF/PPTX
visually itself: (1) structurally, reading the actual saved files back —
a real PDF parsed with `pypdf` and a real PPTX read back with
`python-pptx`, confirming exact colors, fonts, fills, and shapes landed
where intended (teal-deep backgrounds, paper-colored bold title runs,
alternating table row fills, the logo image present) rather than just
trusting the generation code; and (2) genuinely visually, using this
Windows environment's actual installed PowerPoint via COM automation
(`Presentation.SaveAs(..., ppSaveAsPNG)`) to render every slide of a
realistic sample deck to a real PNG and look at it directly — caught and
fixed one real cosmetic bug this way (an invalid `run.font.alignment`
assignment on the title slide's footer run, which doesn't exist as a
`Font` property in python-pptx) before it ever reached a user. The
document-only `body` path (see above) was re-verified through both new
templates afterward to confirm the visual overhaul didn't disturb it.

Document-as-data-source verified end-to-end with a real generated PDF
through the real app: rejected with neither a connection nor a document
selected; a document-only question produces the correct step sequence,
`conversation_id: null` (document-only never creates/chains a
`Conversation`, same as the existing document-attached mode already
excludes follow-ups and the result cache), `row_count: 0`, and — with no
live Anthropic key in this dev environment — degrades gracefully to an
`insight.error` rather than crashing the request, the same defensive
pattern the database path's `explain()` call already used; the history
list/detail endpoints correctly reconstruct it. Also verified as a genuine
regression check against the real local seeded Postgres: a database
question with a document *attached* (the original, still-supported
supplementary mode) still resolves the connection, table allowlist, and
document correctly, reaching real schema discovery before hitting the
same pre-existing, unrelated limitation every database question hits
without a live key (`generate_sql`'s LLM call, unlike `explain()`'s, isn't
exception-wrapped — a real pre-existing gap, confirmed via `git diff` that
not one line of the database branch's existing logic changed).

**Document-only analysis: real chart data, and a diagnosable failure mode**
(`app/agents/insight_agent.py`, `app/agents/planner.py`,
`components/ResultView.tsx`) — a real user's document-only question
("which account is worst performing, create a barchart and pie chart...")
came back with a near-empty report: the explanation step showed "unavailable"
and the downloaded PDF had no findings, no breakdown table, nothing. Reading
the actual pipeline (not just the symptom) turned up two compounding causes,
both now fixed:
- `explain_document_only()`'s JSON parsing was strict enough to crash on the
  most likely real trigger: a user question explicitly asking for a chart
  invites a model to add prose around its JSON ("I can't literally draw a
  chart, but...") or an extra key the schema never asked for — either one
  raised (`json.loads` on non-JSON, or an unexpected keyword argument into
  `Insight(**parsed)`). Fixed with `_parse_json_response()` (salvages the
  outermost `{...}` object from a prose-wrapped response) and an explicit
  known-fields filter before constructing `Insight`, shared with `explain()`
  (the database path) so both are equally robust to a model adding content
  beyond what was asked for.
- Document-only analysis *hardcoded* `by_group: []` and `metrics: {}` —
  every single time, regardless of what the model said — so even a
  perfectly successful explanation could never have produced the requested
  bar/pie chart, and `report_generator.py`/`presentation_generator.py`'s
  "Breakdown" section (which reads `by_group` the exact same way for both
  analysis paths) had nothing to render either. `explain_document_only()`
  now has an explicit, tightly-scoped `by_group` field in its JSON schema:
  the model may populate it ONLY with figures that literally appear in the
  document text (never estimated or invented), only when the question asks
  for a category comparison, and is told plainly that a request to "create
  a chart" is answered by populating this field, not by describing an image
  in prose. Deliberately NOT added to `explain()`'s (the database path's)
  accepted fields — that path already has a REAL `by_group`, computed
  deterministically by `analytics_engine.py`; letting the LLM supply its own
  there would break the "AI never invents a number" rule the rest of this
  app is built around. `planner._sanitize_by_group()` then defends the
  boundary between "model-supplied" and "renders/exports without crashing"
  — coercing a formatted string total (`"18,000"`) to a real float and
  silently dropping any entry that isn't coercible, since this is the one
  chart-data path in the whole app that didn't already come out of
  deterministic code.
- Every insight-generation failure (both paths) was previously swallowed
  into the returned `{"error": ...}` dict alone — nothing was logged
  server-side, and nothing showed up in the audit log, so this exact
  failure would have been just as invisible on a retry. Both `explain()`
  and `explain_document_only()` failures now call `logger.exception()` and
  write a real `AuditLog` row (`action="insight_generation_failed",
  status="error"`), which also means they now count toward the platform
  dashboard's `recent_errors_last_hour` (see "Health snapshot" above) —
  this class of failure is diagnosable from now on instead of only visible
  in an end user's downloaded report.
- **New on the frontend**: a dependency-free pie chart (`PieChart` in
  `ResultView.tsx`, a CSS `conic-gradient` circle plus a legend — no
  charting library, consistent with `GroupBars` right above it and the
  platform analytics dashboard's own bar charts) now renders alongside the
  existing bar chart whenever `by_group` data exists, for BOTH analysis
  paths — there was previously no pie chart anywhere in this app at all.
  Negative totals (a "loss" figure some questions produce) can't be
  represented as a pie slice and are clamped to zero for that chart only;
  the bar chart above it still shows the true signed value.

Verified end-to-end with a real FastAPI generator call (no Anthropic key
needed — `explain_document_only` mocked at the exact seam the real call
would occupy): a prose-wrapped, extra-keyed mock response parses instead of
crashing; a `by_group` response with a comma-formatted string total comes
out the other end as a clean float in the final snapshot with the malformed
sibling entries dropped; the returned `insight` dict carries no stray
`by_group` key; and a simulated failure produces a real, queryable
`AuditLog` row with the actual exception text in `detail.reason` — the exact
piece of information the original failure gave no way to recover.

That `AuditLog` row earned its keep almost immediately: the same real user
hit the fix above, still got "explanation step unavailable" on a fresh
question, and this time the audit log's `detail.reason` said exactly why —
`Expecting value: line 1 column 1 (char 0)`, Python's generic message for
`json.loads("")`. Not malformed JSON this time — the model's response
genuinely had NO text content at all, and the original code gave no way to
tell whether that meant a refusal, an empty response, or a token-budget
cutoff mid-thought. `_extract_text()` now fails LOUD and SPECIFIC the
moment that happens: `Model returned no text content (stop_reason=...,
output_tokens=..., content_block_types=...)`, straight from the response
object's own `stop_reason`/`usage`/block-type fields, before the empty
string ever reaches a JSON parser to produce a confusing error about
syntax that was never the real problem. `max_tokens` was also raised
(`explain()`: 800 → 2048, `explain_document_only()`: 1200 → 4096, both
billed by tokens actually generated, never by this ceiling) on the working
theory — consistent with the specific document-only question involved
("worst account, debts... degrowth percentage in a table", a request that
now also has to produce a `by_group` on top of all eight text fields — see
above) — that the original ceiling cut generation off before any output
text existed. Verified against mocked response objects shaped exactly like
the real Anthropic SDK's (`content`/`stop_reason`/`usage.output_tokens`):
zero content blocks and a present-but-whitespace-only text block both now
raise the specific diagnostic instead of an opaque JSON error, and a
healthy response is unaffected.

That diagnostic paid off on the very next retry: the raised `max_tokens`
ceiling wasn't the fix either. The new, specific error was
`stop_reason='max_tokens', output_tokens=4096, content_block_types=['thinking']`
— the model was spending its ENTIRE budget on an internal `thinking`
content block and never reaching any actual answer text, on every single
retry, regardless of how high `max_tokens` went. Checked against
Anthropic's own current docs rather than guessed at a third time:
`settings.llm_model_reasoning` (`claude-sonnet-5`) has extended thinking
**on by default, with no parameter needed to turn it on** — a genuine
behavior difference from older models, where thinking has always been
strictly opt-in. Both `explain()` and `explain_document_only()` now pass
`thinking={"type": "disabled"}` explicitly, the documented way to turn it
off on this model. Worth noting why this loses nothing: that reasoning was
never shown to a user anyway (`display` defaults to `"omitted"` on this
model — a successful thinking block comes back with empty text even when
it works), and this module's own system prompts already instruct the
model to "do that thinking privately" and output only the finished JSON —
so the exposed reasoning channel was never buying anything here, only
budget it could silently exhaust. Checked the other two real Anthropic
call sites in this codebase (`context_resolver.py`, `query_generator.py`)
for the same exposure — both use `settings.llm_model_fast` (Haiku 4.5),
which is not on Anthropic's thinking-on-by-default model list, so neither
needed this change. Verified against a mocked client, reading back the
actual `thinking` keyword argument on both real call sites and confirming
it's set.

With the crash actually fixed, the real user tried it again and got a
genuine answer back — and reported it as "gibberish" anyway. Reading the
actual PDF this time (not just the symptom) turned up two real, separate
problems, both now fixed:
- **A whole wasted page.** The question itself was long (a 6-section
  extraction prompt), and the PDF printed it twice in full — once as a
  giant bold title, again immediately below as a small "Question: ..."
  line. `routes_artifacts.py`'s new `_short_title()` truncates only the
  oversized headline (100 chars + "…"); the full question is still always
  shown in full right below it in both the PDF and the deck, nothing is
  lost.
- **The real answer, forced into the wrong boxes.** The user asked for
  6 specific named sections (SUMMARY, KEY FACTS, MAIN POINTS, ACTION
  ITEMS, KEY ENTITIES, OPEN QUESTIONS/GAPS). `explain_document_only()`'s
  answer was accurate, but the report's fixed template —
  What/Where/When/Contributors, built for explaining a single computed
  database metric — has no section that fits an open-ended, user-
  structured extraction request, so the real content ended up crammed
  into "Where" and "What contributed" boxes it didn't belong in. That
  mismatch, not the underlying answer, is what read as disorganized
  nonsense. Fixed with a new `Insight.body` field (document-only
  questions only, exactly like `by_group` — `explain()`'s database path
  never sets it): the actual, complete, well-organized answer, explicitly
  instructed to follow the user's OWN requested structure verbatim when
  they gave one (their section names, in their order, "None found" where
  they said so), or sensible headers/bullets when they didn't. `what`
  becomes just a one-line synopsis of it rather than the whole answer
  squeezed into one field. `ResultView.tsx`, `report_generator.py`, and
  `presentation_generator.py` all now render `body` as the primary answer
  (a new "Analysis" section/slide) and skip the Where/When/Contributors
  template entirely when it's present — that template is untouched and
  still used exactly as before for every database-backed question, which
  never sets `body` at all.

Verified end-to-end reproducing the real reported scenario (a 6-section
extraction question against a mocked document-only response shaped
exactly like the new prompt asks for): the final snapshot's `body` matches
what the mock returned; the generated PDF, read back with a real PDF
parser (not just checked for size), contains "Analysis", "SUMMARY", and
"KEY FACTS" from the body while `"Where / When"` and `"What contributed"`
are confirmed absent; the generated deck contains the same section
headers across its slides; and `_short_title()` truncates a long question
while leaving an already-short one byte-for-byte untouched.

`_short_title()` itself had a real bug, caught on the very next report:
the exact multi-part question above (six numbered instructions, each on
its own line) has a `.strip()`-only fix truncate mid-question and land
right after a line break — since `.strip()` only trims the two ends of a
string and leaves every newline in the middle alone, the truncated title
still carried one, and fpdf2's `multi_cell` renders an embedded blank
line as a paragraph break. The result: what should have been one title
line rendered as two, the second looking exactly like an unrelated
second heading directly under the real one — a new, self-inflicted
"gibberish" bug on top of the one this same function was written to fix.
Corrected to `" ".join(question.split())`, which collapses every run of
whitespace — including newlines — to a single space before truncating,
so a multi-line question always produces one clean title line. Verified
against the actual real-world reported question: the fixed function
produces no embedded newline anywhere in its output, while an
already-short single-line question is untouched and a short
*multi-line* question (under the length limit but still newline-bearing)
still gets its newlines collapsed - the bug wasn't specific to long
questions, just more visible on one.

**Structured-table document analysis** (`app/agents/tabular_analysis.py`,
`app/agents/planner.py`, `app/agents/insight_agent.py`) — a real user
uploaded a genuinely large retail spreadsheet (5,232 columns across a
full fiscal year of weekly blocks) and asked for a serious ranking/trend/
projection analysis. Document-only analysis's existing design —
`document_intelligence.py` flattens a table to reading-order text, and
the LLM reasons about that text directly — is explicitly built for
supplementary context, not this: a table that wide blows through
`MAX_EXTRACTED_CHARS` within the first couple of flattened rows, and even
a table small enough to fit is still asking the LLM to mentally group-by
and average prose, the exact kind of LLM arithmetic this app's database
path has never trusted (see `analytics_engine.py`'s docstring — "the LLM
never does arithmetic — it only ever receives numbers that were already
computed"). Manually parsing that file with real pandas code — not the
app — is what actually produced a correct, well-organized answer, which
prompted the obvious question: why doesn't the product do that itself?

Now it does, for the cases where doing it safely is actually possible.
`tabular_analysis.py` gives an uploaded document's real table(s) the
exact same treatment a connected database's query result already gets:
- **XLSX**: each sheet read as real structured data (pandas/openpyxl),
  not flattened text.
- **CSV**: a document kind added alongside PDF/DOCX/XLSX/PPTX
  specifically to get this same treatment — `pandas.read_csv` already
  does header detection and dtype inference natively, so there's exactly
  as little guessing involved as reading a spreadsheet, none of the
  visually-laid-out ambiguity the PDF case below has.
- **DOCX/PPTX**: python-docx/python-pptx already expose an embedded
  table's real cells directly (`table.rows` → `row.cells`, or
  `shape.table`) — no guessing, so pulling one out as a real DataFrame is
  exactly as safe as reading a spreadsheet.
- **PDF is deliberately NOT attempted** — `document_intelligence.py`'s
  own docstring already flags real PDF table structure as a known,
  accepted limitation (needs actual layout analysis, e.g. a new
  `pdfplumber`/`camelot` dependency, and is genuinely unreliable on a
  visually laid-out page). Misreading two visually-adjacent PDF columns
  as one would silently produce a WRONG computed number — worse than the
  existing honest "read it as text and say so" fallback. A PDF still
  gets full document-only analysis; it just doesn't get this upgrade.

A candidate table is only used if it passes real cleanliness checks
(≤120 columns, <20% "Unnamed"/blank headers, at least one usable numeric
column) — the exact 5,232-column real-world case that motivated this
feature is deliberately *rejected*, not guessed at, and falls back to the
original text-based path with an honest note explaining why, rather than
risk computing wrong numbers from a structure a simple heuristic can't
confidently parse. When a table IS usable, `build_profile()` computes —
with real pandas, zero LLM calls — an overall summary, a real
mean-per-group breakdown for every plausible categorical column (store,
agent, region, ..., picked by name-keyword and cardinality heuristics,
a column named in the question itself takes priority), a "best-selling
product per group" cross-tab (which OTHER numeric column has the highest
total within each group), a genuine month-over-month trend when a date-
like column exists, and a threshold band when the question names a
percentage (`"minimum at 60%"` → real `>=60`/`<60` counts, not an
estimate). `data_quality.py`'s `assess()` and `anomaly_detection.py`'s
`detect()` — the exact same functions the database path already trusts —
run against the real parsed table too, replacing document-only's usual
"Not applicable" placeholder for those two steps with genuine findings
when there's real tabular data to check.

The computed profile is handed to `explain_document_only()` as a new
`computed_profile` payload key, with the system prompt updated to treat
it as verified fact on the same trust level as a database's own computed
metrics — explicitly told to use ONLY these numbers and never
"double-check" one against anything read in the document's raw text,
since the profile came from code reading real cells, not from reading
text. The model's job shifts from doing arithmetic on prose to narrating
real numbers by name — the same shift `explain()` already represents for
the database path. The chart (`by_group`) bypasses the model entirely
when a profile exists: `planner.py` builds it straight from the
deterministic breakdown, rather than trusting the model to transcribe a
number into JSON at all, which is strictly safer than the existing
by-hand-from-text fallback still used when no clean table was found.

Verified end-to-end with real files, not just unit-level function calls:
a synthetic clean spreadsheet whose real group-by averages, month-over-
month trend, and threshold count were hand-computed and matched exactly;
real DOCX and PPTX files built with python-docx/python-pptx containing
genuine tables, confirming numeric-string cells get correctly coerced to
real numbers before aggregation; the full `run_analysis` generator run
with the LLM mocked at the exact API boundary, confirming
`computed_profile` actually reaches `explain_document_only()` and the
final snapshot's `row_count`/`metrics`/`by_group`/`data_quality` all
reflect the real computed values, not placeholders; and, critically, the
actual real-world 5,232-column workbook that started this whole feature
re-run through `extract_tables()` directly, confirming it's correctly
*rejected* by the cleanliness checks (zero usable tables found) rather
than silently misparsed into wrong numbers.

**CSV document support** (`app/agents/document_intelligence.py`'s
`extract_csv`, `app/agents/tabular_analysis.py`'s `_extract_csv_tables`)
— a new uploadable document kind alongside PDF/DOCX/XLSX/PPTX, added
after evaluating a contractor-drafted extraction script Joel shared. A
CSV is unambiguously tabular (no header-row guessing, no visually-laid-
out ambiguity a real spreadsheet layout or a scanned PDF page can have),
so it gets the full treatment end to end for free through the existing
dispatch architecture: `extract_csv` produces the same `ExtractionResult`
shape every other format does (decodes `utf-8-sig` with a `latin-1`
fallback for a non-UTF-8 export, a row-count-mismatch note and a row-cap
truncation marker both surfaced inline the same way `extract_xlsx`'s own
truncation marker already is), and `_extract_csv_tables` slots into
`extract_tables()`'s existing dispatch, so a CSV gets the exact same
`computed_profile`-backed deterministic chart XLSX/DOCX/PPTX already get
— zero changes needed in `planner.py` to wire this up.

The same contractor script also reconstructs PDF tables via `pdfplumber`
— deliberately **not** adopted. `tabular_analysis.py`'s own docstring
already explains why real PDF table detection is excluded: it needs
actual layout analysis and is genuinely unreliable on a visually laid-
out page, and since `computed_profile` is the one thing this app tells
the AI to trust without ever double-checking, a misread PDF table could
silently become a wrong number stated with false confidence — worse than
the existing honest text-extraction fallback. `verify_csv_documents.py`
includes a dedicated regression guard for this: `extract_tables(path,
"pdf")` must keep returning `([], [diagnostic])` unconditionally, so this
specific decision can't quietly regress later without a test noticing.

Verified with `verify_csv_documents.py` (9 checks): basic extraction,
mismatched-column-count flagging, row-count truncation, the `latin-1`
encoding fallback, `extract()`'s dispatch, a real CSV's numeric columns
correctly coerced by `tabular_analysis.py`, a too-small/non-tabular CSV
correctly rejected (not silently accepted), the PDF-trust regression
guard above, and a full end-to-end check (a real uploaded CSV through
`_run_document_only_analysis`, confirming the deterministic chart it
produces matches XLSX's). Full backend regression suite green; frontend
lint and `next build` clean.

**Structured-table analysis, round two: recovering the file that started
it all, and making every step genuinely visible** — the same real user
asked, reasonably, why the feature above still didn't touch their actual
5,232-column workbook (it was designed to safely refuse it, not handle
it) and why the Ask screen's step trace still just said generic things
like "Not applicable" instead of showing real work. Both are now fixed:

*Real visibility, not just real computation.* Every step
`_run_document_only_analysis` (`app/agents/planner.py`) emits now carries
specific, real detail instead of a generic sentence: which columns were
picked as the value/group/date column and why, the actual top group and
its real number for every breakdown computed, the real threshold-band
counts, real `data_quality.py` findings (completeness/duplicates/outlier
columns by name), and real `anomaly_detection.py` findings — all rendered
automatically in the existing Ask screen step trace (`ProgressTrace.tsx`
already displayed a step's `detail` field; it just needed a program below
it worth being detailed). When a table gets rejected, the reason is now
just as specific — naming the real column count against the real limit,
or exactly which sheets/tables were tried and why each one didn't
qualify — instead of one generic sentence, so "why didn't this get the
structured treatment" is answered in the product itself, not just in a
chat explanation.

*Recovering a genuinely wide "one block of columns per period" layout.*
The 5,232-column file was correctly and safely rejected, but "safely
reject it" turned out to be a weaker bar than actually possible: its
shape — a normal set of identity columns, then the same set of metric
columns repeated once per month, laid out side by side instead of
stacked — is a common, recognizable spreadsheet pattern (the same shape
`pandas.melt`/`wide_to_long` exist to handle), not an arbitrary mess.
`tabular_analysis.py` now detects it directly: `_find_header_row()`
scores the first ~20 rows of a sheet to find the real header even when
it isn't row 0 (a blank spacer or title row above it, common enough that
assuming row 0 was itself part of the original bug); `_find_repeating_
block_markers()` looks for 3+ real `datetime` values sitting in that
header row (real evidence of a repeating-period layout, not a guess: 1-2
incidental date columns doesn't count); `_reshape_repeating_blocks()`
un-pivots the wide sheet into a long, tidy table — one row per (identity,
period) — the same real values, just reshaped, never estimated. A too-
wide sheet always goes through this path before being rejected, and is
only rejected if no such pattern is actually found.

Getting this right took several real, caught-in-testing fixes, not one
clean pass:
- A block's own sub-columns can repeat internally (that file's monthly
  block had "Customers Served, Target, MTD Achievement, 1st, 2nd, ...
  31st" columns repeated once per product) — `pd.concat` raises on
  duplicate column labels, caught immediately by actually running this
  against the real file. Fixed by keeping only the first occurrence of
  each name per block; the spreadsheet gives no way to tell which
  product a later repeat belongs to beyond column position, so keeping
  the first is honest about that limit rather than inventing a
  distinguishing suffix the data doesn't support.
- The date-marked column itself is not just a period *label* — its own
  values were the real metric being tracked for that period (that file's
  actual composite score). An early version discarded it, keeping only
  the date; fixed by including it in the reshape under a generic "value"
  name, and by `pick_value_columns()` explicitly prioritizing a column
  literally named "value"/"score"/etc. over raw column order.
- `pick_best_table()` was choosing by raw cell count alone, which
  confidently handed the whole analysis to a completely unfilled
  15,738-row KPI-tracking template sheet elsewhere in the same workbook —
  more raw cells than the real data sheet, but virtually all zeros. Fixed
  with `_real_data_density()`: non-null, non-zero cells in non-ID
  columns, so an empty template can no longer look richer than real data
  just by being long (and a plain sequential "No" row-number column,
  which is non-zero for nearly every row regardless of whether the row
  has real data, doesn't get to inflate the score either).
- Reading a sheet with `header=None` (needed so the header-row detector
  can inspect row 0 itself as a candidate) meant pandas never got its
  usual chance to infer real numeric dtype excluding the header text —
  slicing the header back out afterward left every column typed as
  `object`, breaking value/threshold detection for the ordinary,
  already-working case too. Fixed by running the same
  `_coerce_numeric_columns()` DOCX/PPTX already needed (their cells are
  always strings) on every XLSX table too.
- A sparse numeric column (a `Target` figure only set for some agents,
  a mostly-blank daily breakdown column) can sit right at the edge of
  that same coercion's 60% threshold and stay text-typed without being a
  real category — `pick_group_columns()` was treating a few of these as
  meaningful business dimensions ("top Target: 1250"). Fixed by also
  requiring a real candidate's non-null values be overwhelmingly *not*
  numeric-parseable, not just object-dtyped.
- The threshold-band feature (`"minimum at 60%"`) only fired when the
  value column's NAME matched a percent-like keyword, which a reshaped
  sheet's generically-named "value" column never will. Fixed to also
  accept a column whose actual values are plausibly percentage-scaled
  (comfortably under 1000), not just a lucky name.

Every one of these was caught by actually running the real 5,232-column
file through the pipeline and checking the numbers against the same
by-hand analysis that originally motivated this feature — not by
reasoning about the code in the abstract. The final, fully-fixed result
reproduces that by-hand analysis exactly: 804 rows recovered (67 real
agents × 12 real months, correctly excluding both the ~280 blank roster
placeholder rows and the 7 future unfilled months), the same top store
(Trend Setter Mall) and the same real score, and the same real monthly
trend (72.5 → 76.5 → 34.4 → 72.4 → 76.4) including the same sharp,
isolated June anomaly the original manual analysis flagged as more likely
a data issue than a real business collapse.

**Structured-table analysis, round three: a genuinely new JSON failure
mode, and closing the "why does it think my file is empty" loop for
good** — the same real user tried it again after round two shipped and
got a confidently wrong answer ("this workbook is a blank template with
no data") for a file that very much has data. Two real, separate things
were going on, both found from the tenant's own Audit log rather than
guessed at:

- A **genuinely new failure mode**: one attempt's `insight generation
  failed` entry read `Invalid control character at: line 1 column 479`
  — not the empty-response failure round one fixed, and not a formatting
  mismatch round two's `body` field was built for. This is Python's
  `json` module refusing an otherwise well-formed response over a single
  technicality: the JSON spec requires a newline *inside* a string value
  to be escaped (`\n`), but `SYSTEM_PROMPT_DOCUMENT_ONLY`'s own
  instructions ask the model to use real blank lines and `"- "` bullets
  in `body` for readability — exactly the shape of output most likely to
  tempt a model into emitting a raw, unescaped line break instead of the
  escaped form. `_parse_json_response()` now calls `json.loads(...,
  strict=False)` — the standard, documented way to accept a control
  character inside a string rather than reject an otherwise-valid
  response over it. Reproduced directly from the real audit log message
  before fixing it: a JSON string built with a literal embedded newline
  confirmed to fail under Python's default strict parsing with the exact
  same error, then confirmed to parse correctly once `strict=False` was
  applied.
- **Answering "did it even try" without another round of screenshots**:
  the *other* real attempt that produced the wrong "empty template"
  answer had no failed-insight audit entry at all — the model returned
  valid JSON, just a wrong conclusion, which meant there was no way to
  tell, from the audit log alone, whether structured extraction had even
  been attempted for that specific request. The `document_only_query_
  executed` audit entry now records `structured_table_used` and, when
  true, the real parsed `table_shape` — so "did this one actually get
  real computed data, or was it reading text" is answered directly from
  the same Audit log screen already being checked for insight failures,
  without needing to ask for a different piece of evidence each time.

**Risk scan** (`app/agents/risk_scan.py`, `/scan/stream`) — proactive
"find anything unusual across everything" scanning, answering "give me the
top five risks" without the user already knowing which table or question
to ask about, rather than anomaly detection only ever running against the
current question's result. Zero LLM calls: it's possible precisely because
the query shape is always the same regardless of table (group by two
guessed dimension columns, sum a guessed value column), so there's no
natural-language question to translate. Every other layer stays in place —
schema comes from the same policy-filtered `discover_schema`, the built SQL
still goes through `validate_readonly_sql`, results go through
`output_guard`, and a row-scope check excludes (not aborts the whole scan
for) any table where the caller's row-level restriction can't be verified
in the result. Bounded to `MAX_TABLES_SCANNED` (10) tables per scan, and
reuses the same per-user rate limit / per-tenant concurrency cap as
`/ask/stream`. Verified with a standalone test of the SQL-building and
row-scope-filtering logic (proper SQL string-literal escaping, not Python's
`repr()`; a row-scope column absent from a given table correctly adds no
filter, matching the main pipeline's existing semantics; multiple scope
columns AND-combine correctly) plus the confidence-based ranking, all
independent of the FastAPI/DB/pandas stack.

**Outputs**
- PDF report, PPTX presentation, CSV/XLSX export — all generated from the
  same already-computed, already-authorized result snapshot, never a fresh
  unrestricted query.
- Email delivery: sending to yourself is auto-approved; any other
  recipient requires explicit confirmation. **A tenant-level outbound
  policy** (a security-review fix — the confirm flag was the *only*
  control, and it's client-asserted) sits above that: an admin sets it on
  the Security page (`PATCH /auth/team/email-policy`) to `open` (default,
  unchanged — confirm-per-external-recipient), `self_only` (every
  recipient except the sender's own address is blocked outright), or
  `domain_allowlist` (also allows a list of domains). Enforced in
  `send_report` for real, not just in the UI; a tenant that predates the
  column reads as `open`. Verified: `open` still confirms-then-sends;
  `self_only` blocks every external recipient even when confirmed;
  `domain_allowlist` sends to the listed domains and the sender's own
  address and blocks the rest (domains normalized — case, leading `@`);
  a bad mode / empty allowlist / malformed domain is a `400`; a non-admin
  can read the policy but not change it. Two backends behind
  `EMAIL_PROVIDER`: `console` (default) logs instead of sending; `smtp` is
  a real, generic SMTP backend (stdlib `smtplib`, no vendor SDK) —
  deliberately provider-agnostic rather than committing to one specific
  API, so it works with Gmail (an app password), any transactional
  provider's SMTP relay (Postmark/SendGrid/SES/Resend all offer one), or a
  domain's own mail hosting. A failed real send (bad credentials, refused
  recipient, connection timeout) degrades to a clean, logged `"failed"`
  result surfaced back to the user — not an unhandled exception turning
  into a 500 for what's a completely ordinary "delivery didn't work"
  outcome. Verified against a stubbed `smtplib.SMTP` client (exact command
  sequence and MIME structure, including attachment content-type
  guessing) before a live account existed; **now also verified against a
  real Resend account in production** — a real domain-verified sender, a
  real registration triggering a real welcome email that actually arrived
  in a real inbox. One genuine deployment gotcha hit and fixed along the
  way: Railway blocks outbound traffic on the standard SMTP port (587) to
  curb platform abuse, which surfaced as `TimeoutError: timed out` in the
  backend's own logs — not a credentials or DNS problem at all. Fixed by
  switching to Resend's alternate STARTTLS port (`2587`), which exists
  specifically because this exact kind of provider-side port blocking is
  common; no code change needed, purely a `SMTP_PORT` env var fix.
  Separately verified the failure-degrades-cleanly path against a *real*
  connection failure (a port nothing listens on) through the real FastAPI
  route, confirming a 200 with `status: "failed"` rather than a crash,
  and a real `EmailDeliveryLog` row written either way.

  **Every email now renders as a branded HTML message**
  (`_render_html_email` in `app/agents/email_delivery.py`), not the bare
  plain text it used to be — a header logo and a "Made by Meridian"
  footer, applied uniformly to every email this backend sends (welcome,
  invites, owner notifications, MFA recovery, admin-triggered password
  reset, and the AI agent's "email me this report" feature) without any
  of those callers needing to change at all — purely a presentation layer
  added at the transport level. Sent as a real `multipart/alternative`
  (plain text + HTML, the plain-text part completely unchanged) so every
  client can render it and nothing looks broken to a mail client that
  doesn't render HTML. The header is the real logo image
  (`frontend/public/brand/meridian-logo-email.png`, served as a static
  asset off the frontend and referenced by an absolute
  `https://www.getmeridiananalytics.com/...` URL so it works from any
  mail client, not just ones that can reach the app itself) — a
  deliberate choice over the earlier CSS-styled text badge, even though
  it means some clients (desktop Outlook, mainly) show a blank space
  until the recipient clicks "show images" rather than rendering
  instantly; `alt="Meridian"` plus explicit `width`/`height` keep that
  state from collapsing to nothing. Verified by constructing a real
  message through the actual `SmtpEmailBackend` (with `smtplib.SMTP`
  mocked) and confirming the resulting MIME tree is correctly
  `multipart/mixed` → `multipart/alternative` (plain + html) →
  attachment, that the plain-text part is byte-for-byte what it always
  was, and that the HTML part contains the expected branding and dynamic
  content (founder name, company name) — then confirmed for real against
  the actual production `send_welcome_email` path. The logo swap itself
  is covered separately by `verify_email_branding.py` (3 checks): the
  rendered shell embeds the real `<img>` and not the old text badge, the
  image carries explicit width/height, and the real `SmtpEmailBackend`
  send path embeds it too (not just the template function in isolation).

  **Sender name** — the `From` header was a bare address
  (`hello@getmeridiananalytics.com`) with no display name, so most inboxes
  showed the local part, `hello`, standing in for a sender name since
  there wasn't one. Fixed with `email.utils.formataddr(("Meridian",
  from_address))`, which produces a correctly quoted/encoded `"Meridian
  <hello@getmeridiananalytics.com>"` header per RFC 2822 — every client
  now shows the brand name a recipient actually recognizes. Verified
  against a stubbed `smtplib.SMTP` client, reading the constructed
  message's own `From` header back.

  **Favicon** (`frontend/app/icon.svg`, `frontend/app/favicon.ico`) — a
  simple on-brand mark (a rounded square in the app's own `--teal-deep`
  color with a bold "M"), picked up automatically by Next.js's App Router
  file-convention (no code/metadata change needed) and shown as the
  browser tab icon everywhere, replacing the framework's default
  placeholder. The `.ico` is a genuinely multi-resolution icon (16/32/48/
  64px, via Pillow, rendered from a single sharp high-resolution source
  rather than upscaling a tiny one) for crisp rendering across browser
  tabs, bookmarks, and OS-level icon caches that still request the legacy
  format directly.

  **Downloads are authenticated now, not a public static mount**
  (`app/main.py`, `app/api/routes_artifacts.py`, `app/security/auth.py`) —
  a security-review finding, fixed. Generated reports/presentations/
  exports were served by a plain `app.mount("/artifacts",
  StaticFiles(...))` with **no authentication at all**, and the on-disk
  filenames were only `uuid4().hex[:8]` — 32 bits. Any tenant's report
  (its business data, generated SQL, metrics, anomalies) was a guessable
  URL away from anyone on the internet, with no expiry and no `Referer`
  protection. That mount is gone. Downloads now go through
  `GET /artifacts/file/{id}?token=…`, where the token is a signed,
  1-hour, single-artifact JWT (`create_artifact_download_token`,
  HS256, same secret as session tokens) minted only by the generate/
  list endpoints *after* they've confirmed the caller's tenant owns the
  artifact. The download route serves the file with the correct
  `Content-Type`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, and a `Content-Disposition: attachment`.
  On-disk names are now the full `uuid4().hex` too, as defence in depth.
  The frontend needed no change — the `url` field it already prefixes
  with `API_BASE` just carries the token now. Object storage + signed
  URLs is still the right end state; this closes the hole without it.
  Verified end-to-end against a real SQLite DB + FastAPI: generating a
  report returns an authenticated URL that downloads the real PDF
  (correct headers), a missing/garbage/wrong-artifact/expired token each
  gets a 403, the old `/artifacts/<filename>` path now 404s, and the
  Library (`/history/artifacts`) listing uses the same authenticated URL.

**Legal pages** (`frontend/app/privacy/page.tsx`, `frontend/app/terms/page.tsx`)
— a real Privacy Policy and Terms of Service, linked from the marketing
footer and referenced in the registration form's consent line ("By
creating an account, you agree to..."). Written by inspecting what the
codebase actually does rather than generic boilerplate — the third-party
sub-processor list (Anthropic, Paystack, Resend, Railway), the
read-only/encryption/audit claims, the 7-day refund window, and the
per-plan usage caps are all real, current facts about this specific app,
not filled-in placeholders. Both pages say plainly, at the top, that they
have not been reviewed by a lawyer — this closes the "the software
matches what the document claims" gap, not the "is this document legally
sufficient/NDPR-compliant" gap, which needs an actual lawyer, not more
code. Public routes (`AuthGate.tsx`), no sidebar chrome (`Sidebar.tsx`),
same treatment as `/status`.

**Product analytics** (`GET /platform/analytics` in `routes_platform.py`,
`frontend/app/platform/analytics/page.tsx`) — a business-metrics dashboard
in the internal admin panel: total/active tenant counts, signups and
questions asked per day over the last 30 days, an activation funnel
(registered → connected a data source or uploaded a document → asked a
question → subscribed), tenant breakdowns by tier and plan, generated-
artifact counts by kind, and the most recent signups. Deliberately built
first-party from data this app already collects for other reasons
(`Tenant`, `QueryRecord`, `DataSourceConnection`, `UploadedDocument`,
`GeneratedArtifact`) rather than wiring in a third-party analytics SDK
(PostHog/Mixpanel/etc.) — that would mean real user behavioral data
leaving the platform to a new sub-processor, which would need disclosing
in the just-shipped Privacy Policy, plus a new vendor relationship and API
key to manage, for what this stage actually needs. Charts are plain CSS
divs sized by percentage, no charting library — consistent with the rest
of this codebase's habit of reaching for a dependency only when plain
code genuinely can't do the job (same reasoning as the PDF/PPTX export
code not pulling in matplotlib). Daily buckets are computed in Python
rather than a SQL `GROUP BY`, so the same code behaves identically on
SQLite (dev) and Postgres (prod) without depending on either dialect's
date-truncation functions. Aggregated counts only — never a single row of
one tenant's actual business data, the same boundary the rest of this
staff-only panel already respects.

**Redis (optional, `app/security/redis_client.py`)** — the rate limiter,
login cooldown, and query cache below were originally in-process-only
(correct for one instance, silently weaker behind multiple workers/
replicas — each enforced its own independent state). All three now share
one opt-in Redis backend: unset `REDIS_URL` and every one of them falls
back to its original in-process behavior automatically (a plain
`pip install` dev setup with no Redis running is completely unaffected);
set it to a real Redis URL and all three become genuinely global across
every process and replica at once, since it's the same category of fix
for all three. Deliberately avoids Lua scripts/WATCH-MULTI transactions
in favor of plain atomic single-command operations (`ZADD`/`INCR`/
`HINCRBY`) with a self-correcting rollback on the rare race — see the
class docstrings in `rate_limit.py`/`login_cooldown.py` for exactly why
that's still correct for this use case (a rate limiter doesn't need the
linearizability a payment or a row-scope check would) and why it was
chosen over Lua specifically (avoids pulling in a native Lua interpreter
dependency purely to test the scripts locally). Every Redis call fails
open on a connection error — logged, but never blocking the request or
crashing the app, since all three are secondary protections layered on
top of the real security boundary (auth, tenant scoping, subscription
gating), none of which touch Redis at all; confirmed fast (~1s, not the
15s redis-py's default retry policy would otherwise silently add) by
explicitly disabling retries on the shared client.

Verified against a real Redis protocol implementation (`fakeredis`, not a
mock of this app's own logic): the rate limiter admits exactly the
configured count and rejects the next with the state directly inspected
in Redis (not just via the app's own success/failure return values); the
concurrency limiter same; login cooldown produces the identical behavior
the in-process version already had (5 free failures, escalating cooldown,
success clears history) with tenant/platform login cooldowns confirmed
isolated in separate Redis keyspaces despite sharing one Redis instance;
the query cache hits/misses correctly including the security-critical
row_scope-isolation case; and a genuinely unreachable Redis connection
was confirmed to fail open in ~1s rather than hang or crash. Also
reverified the REDIS_URL-unset path still picks the original in-process
classes with zero behavior change.

**HTTP response headers & the interactive docs** (`app/main.py`, a
security-review fix — there were no security headers at all). A small
middleware now sets `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (which matters
specifically for the signed artifact-download URLs), and
`Cross-Origin-Opener-Policy: same-origin` on every response, plus
`Strict-Transport-Security` when the request arrived over HTTPS
(`X-Forwarded-Proto`, so never on plain-http local dev). No full CSP:
this API returns JSON and file downloads, never attacker-controlled HTML.
Separately, FastAPI's interactive docs (`/docs`, `/redoc`,
`/openapi.json`) — which publish the whole API surface — are **disabled
when `ENVIRONMENT=production`** and kept in development where they're
useful. Verified: the header set is present on a plain response with no
HSTS; HSTS appears with `X-Forwarded-Proto: https`; `/docs` is `200` in
dev and `404` in production; and `/ask/stream` still streams SSE (and
carries the headers) through the middleware.

**Rate & concurrency limits** (`app/security/rate_limit.py`) — `/ask/stream`
is the one endpoint that costs a real LLM call plus a live customer-DB
query per request, so it's rate-limited per user (sliding window,
`ASK_RATE_LIMIT_PER_USER_PER_MINUTE`, default 10/min) and concurrency-capped
per tenant (`ASK_MAX_CONCURRENT_PER_TENANT`, default 3 at once). This
complements, not duplicates, the per-query bounds that already existed:
`query_validator.py` injects a `LIMIT` into every generated query and each
connector enforces `QUERY_TIMEOUT_SECONDS` — those cap the cost of *one*
query, this caps *how many* run.

**Login cooldown** (`app/security/login_cooldown.py`) — brute-force /
credential-stuffing protection on both login endpoints (`/auth/login` and
`/platform/login`), which had none before. Tuned deliberately so it can
never itself become a churn risk: it's keyed by the account being attempted
(email), never by IP, so one guesser never collateral-damages everyone
behind a shared office/VPN address; the first `LOGIN_FREE_ATTEMPTS`
(default 5) wrong passwords cost nothing at all — no delay, no error beyond
the normal 401 — since typos and stale autofill are routine, not attacks;
only after that does a cooldown kick in, starting at
`LOGIN_COOLDOWN_BASE_SECONDS` (default 15s) and doubling with each further
failure up to `LOGIN_COOLDOWN_MAX_SECONDS` (default 15 min) — long enough
that guessing thousands of passwords is infeasible, but the account is
never permanently locked: even a correct password is turned away with a
`429` and a plain-English retry time while a cooldown is active (otherwise
a lucky or automated guess mid-cooldown would slip straight through), and
the very next attempt after a real success clears the account's history
completely. Verified end-to-end against the real app and SQLite DB: 5 free
failures stay plain 401s, the 6th is blocked with `429 Too many failed
attempts. Try again in 15s.`, a correct password is also blocked mid-
cooldown, an unrelated account is unaffected, and the account logs in
normally the moment the cooldown expires.

A security-review follow-up added the layer the per-email guard
structurally can't provide: a **per-client-IP** failed-login guard
(`LOGIN_IP_FREE_ATTEMPTS`, default 50), applied to `/auth/login` and
`/platform/login` *alongside* the per-email one. Per-email keying is blind
to distributed credential stuffing — one password tried once against each
of 10,000 different emails from a single source costs nothing under it.
The IP guard trips on that. Its budget is much larger because a shared
office / VPN / NAT egress carries many real users, and it uses the same
escalating-but-never-hard-locking backoff. The client IP comes from
`X-Forwarded-For` (`app/security/ip_throttle.py`) — spoofable if the
front proxy isn't trusted, so this is a defence-in-depth abuse brake, not
a hard boundary. That module also adds a per-IP hourly cap on
`POST /auth/register` (`REGISTER_RATE_LIMIT_PER_IP_PER_HOUR`, default 5),
which previously had no throttle at all — each call creates a tenant, a
user, a unique subdomain, and a welcome email. Verified end-to-end: the
4th register from one IP (test cap 3) is a `429`; a different
`X-Forwarded-For` is a fresh bucket; 3 failed logins across 3 *different*
emails from one IP followed by a 4th against an untouched email is a
`429` from the IP guard (not the per-email one); a different IP is
unaffected; a correct password clears the IP guard.

**Query result cache** (`app/agents/query_cache.py`) — an identical fresh
(non-follow-up) question skips the SQL-generation LLM call, the live DB
query, and the insight-explanation LLM call entirely, reusing the prior
result for `ASK_CACHE_TTL_SECONDS` (default 5 min). The cache key is
deliberately over-inclusive on anything security-relevant: it includes the
connection's *current* table/column policy (so a policy change immediately
makes old cache entries unreachable, never served past the change that
should have blocked them) and the caller's row-level scope (so two users
under different row restrictions can never share an entry) — verified with
a standalone test exercising exactly those isolation properties (different
tenant/connection/row_scope/column_policy/table_allowlist each correctly
miss) plus TTL expiry and eviction, independent of the FastAPI/DB stack.
Every cache hit still gets its own fresh `QueryRecord`, so it shows up as
its own entry in Analyses history and "Create from this analysis" still
works — the only thing skipped is the actual re-computation. Follow-up
questions are never cached (their meaning depends on evolving conversation
context) and a cache-served answer can't be chained into a follow-up
directly for the same reason — ask a new question to continue.

**Follow-up threading: the first question's `conversation_id` was silently
NULL** (`app/agents/planner.py`'s `run_analysis()`) — reading the
database-backed Ask path turned up a real bug in how a brand-new
conversation thread was persisted. When a tenant asked a fresh question
(no `conversation_id` passed in), `run_analysis()` built and `db.add()`-ed
the `QueryRecord` with `conversation_id=conversation.id if conversation
else None` *before* the new `Conversation` object was created a few lines
later. `Conversation.id`'s default is a Python-side `uuid.uuid4()` callable
that SQLAlchemy only resolves at flush time, so at the moment the
`QueryRecord` was constructed `conversation` was still `None` — and the
row was written with `conversation_id = NULL` permanently. The net effect:
every thread's *first* question had a null `conversation_id` in its own
database record forever, and only the follow-ups after it correctly showed
the real link. Anything reading `QueryRecord.conversation_id` saw the gap —
notably `GET /history/analyses/{id}` (`routes_history.py`), which returned
`conversation_id: null` when reopening the analysis that actually started
the thread.

The fix is the same `db.add(parent) → db.flush() → db.add(child)` ordering
already used in `routes_monitor.py`, `routes_support.py`, and
`routes_platform.py` for exactly this parent-id-before-child situation:
the new `Conversation` is created, added, and flushed (forcing its id to
be assigned) *before* the `QueryRecord` that references it is built, and
the `QueryRecord` now uses `conversation.id` directly rather than the
`... if conversation else None` guard. The `conversation.context`
assignment (`build_context_snapshot(...)`) is unchanged. The sibling
document-only path (`_run_document_only_analysis`) never had this bug —
it deliberately never creates or chains a `Conversation` and hard-codes
`conversation_id=None`.

Verified end-to-end against a real SQLite database and the real
`run_analysis()` generator (only the warehouse connector, schema
discovery, and the three LLM calls stubbed — the `QueryRecord`/
`Conversation` persistence under test is fully real): a fresh question
with no `conversation_id` now stores a real, non-null UUID
`QueryRecord.conversation_id` that matches the single `Conversation` row
actually created; a follow-up on that same `conversation_id` reuses the
same row and both `QueryRecord`s show the same real id; and the same
check run against the pre-fix code fails exactly where expected
(`first QueryRecord.conversation_id is NULL`), confirming the test
catches the regression rather than passing vacuously.

**Saved/pinned analyses** (`app/db/models.py`'s `PinnedAnalysis`, `/history/analyses/{id}/pin`)
— star any past analysis from Analyses history (list view or the reopened
detail view) to keep it in a "Saved" filter for quick access, without
scrolling the full shared history. Deliberately per-**user**, not
per-tenant like `QueryRecord`/the audit log: everyone on a team already
sees every analysis in the shared history, but which of those matter
enough to keep at a glance is a personal judgment call — the same
"starred" convention as Gmail/GitHub, not a team-wide fact, so two users
on the same tenant can pin entirely different analyses without affecting
each other. `PUT`/`DELETE .../pin` are both idempotent (pinning an
already-pinned analysis, or unpinning one that was never pinned, is a
no-op 200, not an error) so the frontend's star button can toggle on a
single click without tracking prior state itself. No FK from
`PinnedAnalysis` to `QueryRecord` — matching `QueryRecord`'s own
`connection_id`/`tenant_id` convention of plain string columns, not FK
constraints — since a pin outliving its analysis is harmless: listing
always joins pins against whatever analyses still exist, never the
reverse. Verified end-to-end against a real local SQLite database and the
real FastAPI app (not reimplemented logic): pin/unpin/re-pin idempotency,
the `pinned_only` filter, the per-analysis detail view, and — the one
property actually worth a dedicated check — that two different users on
the *same* tenant each see the shared analysis history but maintain fully
independent pin state on it.

**Audit log** — every query, rejection, connection event, and artifact
generation, tenant-scoped, queryable via `/audit` (the `limit` query
param is clamped to a hard ceiling, here and on `/history/*` and
`/platform/audit` — a security-review pass, so `?limit=99999999` can't
ask for the whole table). Hash-chained
(`app/audit/logger.py`): each entry's hash covers its own fields plus the
previous entry's hash, so editing, deleting, or inserting a row out of band
breaks the chain from that point forward — `GET /audit/verify` recomputes
it and reports exactly where. This is tamper-*evidence*, not
tamper-*proofing*: the hash algorithm lives in the same codebase and
database it protects, so it won't catch someone with DB write access and
knowledge of this code rewriting a run of rows and recomputing every hash
after them consistently. It does catch anything short of that — accidental
edits, an app bug writing to the table directly, a careless tamper attempt,
corruption. A genuinely tamper-proof trail needs the chain's head hash
anchored outside this database entirely — now implemented, see
**Externally-anchored checkpoints** below. Full caveats, including a
known race on concurrent writers, are in the module docstring.

**Externally-anchored checkpoints** (`app/audit/anchor.py`,
`POST /platform/audit/checkpoint`, owner-only) — the specific fix for the
gap the paragraph above calls out. `verify_chain()` alone can't tell an
untouched hash chain apart from a *fabricated-but-internally-consistent
replacement* — someone with DB write access could delete every row and
insert a brand-new chain from a fresh genesis, and verification would
report `intact: True`, since a self-consistent-with-itself chain is all
that check can see. A checkpoint closes that: it computes a single root
hash over every tenant's current chain head and commits it to a real file
in an external GitHub repo — a system this app can only append to via an
explicit token, whose own commit history is nobody's to unilaterally
rewrite the way a database is. Verifying (`GET
/platform/audit/checkpoint/latest`, open to any staff role) checks
whether each anchored hash still literally appears in that tenant's
current chain — a replacement chain built from different content will
never happen to reproduce the exact same hash at the exact same point,
since the hash covers full entry content down to a timestamp.

Writes go to a dedicated branch (not the default branch), created
automatically from the repo's tip on first publish — deliberately not
main. A real, live discovery while building this, not a design
guess: this exact repo has PR-required branch protection on `main` with
`enforce_admins: true`, and a direct Contents API write there is rejected
with a 409 regardless of the token's own permissions. Deliberately
admin-triggered, not an automatic timer — this app has no job scheduler;
pair it with an external cron (a scheduled GitHub Action, a Railway cron
service) for genuinely periodic anchoring.

Verified two ways: the fabrication-detection property itself (build a
tenant's real chain, checkpoint it, then delete every row and replace it
with a brand-new self-consistent fabricated chain — confirmed
`verify_chain()` alone reports the fabrication as `intact: True`, exactly
the gap this closes, and confirmed `verify_checkpoint()` correctly flags
it as unverified since the anchored hash no longer appears anywhere in
the replacement chain) against a real local database; and the GitHub
integration itself — not mocked — with a real publish, real read-back,
and real verification against this actual repository during development,
cleaned up afterward via the same API. 17/17 checks passed.

**Automated uptime monitoring** (`app/api/routes_monitor.py`,
`scripts/uptime_monitor.py`, [docs/UPTIME_MONITORING.md](docs/UPTIME_MONITORING.md))
— the actual fix for `SystemIncident`'s own docstring calling out that
incidents were entirely human-logged. Same "no job scheduler in this app"
constraint as the audit checkpoint above, so the real fix is the same
shape: a small standalone script, run on a Railway Cron Job (a separate
scheduled service, not a thread inside the API process — the API being
fully down must still get noticed, which an in-process check could never
manage), checks the live public status page and this API's own `/health`
from the outside, then reports the result to `POST /monitor/heartbeat`.
That endpoint opens a real `SystemIncident` the first time a check fails
(`created_by_staff_id` left null — that's what distinguishes "automated"
from "a human logged this" in the platform Activity view), does nothing
on every subsequent failing run while that same outage is still open
(never spams duplicate incidents), and auto-resolves it the first time a
check passes again. Authenticated by a shared secret
(`UPTIME_MONITOR_SECRET`), not a human platform-staff login — a scheduled
script has no human to log in as, same category of machine credential as
the Paystack webhook's HMAC signature elsewhere in this app; unset
(default) makes the endpoint 503 unconditionally rather than accepting a
stray or guessed request. Honest about what this is NOT: single-region
(Railway Cron Jobs run from one region), no alerting (email/SMS/Slack) —
this only ever gets checked by someone looking at the status page or
Activity view. Pair with a real third-party monitor (UptimeRobot, Better
Stack) for either of those specifically; this in-house version exists
because it plugs directly into the incident model this app already has
and needs no third-party account, not because it's a superset of what a
dedicated monitoring service gives you.

Verified two ways: a real end-to-end test against a local SQLite DB (9
checks — wrong/missing secret rejected, a healthy heartbeat with nothing
open does nothing, the first failing heartbeat opens an incident, a
second failing heartbeat during the same outage does NOT duplicate it,
the auto-incident is visible on the public `/status` endpoint exactly
like a manual one, a healthy heartbeat resolves it, the status page
reports operational again, a fresh outage after recovery opens a
genuinely new incident rather than reusing the resolved one, and an
unconfigured secret correctly 503s); and the standalone script itself run
for real against a live local server — a genuine simulated outage
(pointing it at a port nothing was listening on) correctly detected and
reported, confirmed visible on `/status`, and confirmed auto-resolved on
the next run once the real URL was restored.

**Tenant account self-service** (`PATCH /auth/me/display-name`, `PATCH
/auth/me/email`, `PATCH /auth/me/password`, `app/account/page.tsx`) — any
tenant user can set a display name (shown instead of their raw email in
the Home dashboard greeting and elsewhere around the app once set),
change their own email, and change their own password, all without
involving an admin. The display name has a **60-day cooldown** (nullable
`display_name_changed_at` timestamp on `User`, `DISPLAY_NAME_COOLDOWN_DAYS`
in `routes_auth.py`) rather than a hard cap — cosmetic, not an identity
control, so it just needs to stop being churned every few minutes, not be
locked forever; `GET /auth/me` returns `display_name_change_available` +
`display_name_next_change_at` so the frontend can grey out the field and
say exactly when it reopens rather than the user finding out only on
submit. Email change is deliberately **one-time**: a nullable
`email_changed_at` timestamp on `User` is set the first time it's used and
checked on every subsequent attempt, so a second change is rejected with a
clear error rather than silently allowed — the intent is "fix a typo once,"
not an open-ended identity swap. Password change requires the current
password, same as any other in-session credential change. Both email and
password changes notify every admin on the tenant (`notify_owners`) so a
change nobody recognizes doesn't go unnoticed.

**Admin-triggered password reset** (`POST /platform/tenants/{id}/users/
{user_id}/reset-password`, owner/support, `POST /auth/password-reset/
redeem`, `app/reset-password/page.tsx`) — for a tenant user who's locked
out and can't use the normal "change my password" flow above because they
can't sign in at all. Platform staff trigger it from the tenant's
sub-accounts list; the user gets an emailed link (not a numeric code —
reuses the same signed pre-auth JWT pattern as MFA recovery, `purpose=
"password_reset"`, 30-minute expiry) that sets a new password and signs
them straight in on redemption. The token is single-purpose (a
`mfa_recovery` or `handoff` token can't be replayed here and vice versa)
and tenant/user-bound, so redeeming it can't be pointed at a different
account.

**Subscription-expiring-soon banner** (`components/
SubscriptionExpiryBanner.tsx`) — a persistent bar (same pattern as the
existing MFA-setup warning banner, not a dismissible toast) that appears
on every screen once a tenant's subscription is within 7 days of
`subscription_expires_at`, with a direct link to Billing. This is the
"you can see it yourself" complement to the existing automatic email/bell
renewal reminder (`maybe_send_expiry_reminder`) — same underlying data,
just always visible rather than something that has to land in an inbox.

**Platform billing detail & fraud/abuse override** (extends `GET
/platform/tenants`, `POST /platform/tenants/{id}/deactivate-and-refund`,
owner-only) — the tenant list in the internal admin panel now shows the
comped plan amount, the last Paystack transaction reference, and the
Paystack customer code alongside the existing subscribed/expires dates,
so "how much, when, and where to look it up directly in Paystack" is all
on one screen without cross-referencing the Paystack dashboard by hand.
Separately, an owner-only "Deactivate & refund" action exists for
confirmed fraud/abuse: it disables the real Paystack subscription
(`paystack.disable_subscription`), refunds the last transaction in full
(`paystack.refund_transaction`), and marks the tenant `cancelled` — one
step, not "cancel, then separately remember to refund." A reason is
required and is written to the audit log; the action is gated to active
subscriptions only, so it can't be fired twice or against a tenant that
was never actually paying.

Verified with three new real-DB regression scripts (24 checks total):
`verify_account_self_service.py` (9 — display name including the 60-day
cooldown rejecting an immediate second change and allowing one again once
the cooldown has genuinely elapsed, one-time email change including the
second-attempt rejection, password change with correct/incorrect
current-password, and the `.test`-domain `EmailStr` gotcha worked around
by using `.example.com`-style addresses), `verify_admin_
password_reset.py` (8 — staff-trigger and redeem happy path, tenant/user
mismatch guard, replay-after-redeem rejection, wrong-purpose-token
rejection), and `verify_platform_billing_ops.py` (7 — billing detail
exposure, deactivate-and-refund happy path, refund-API-failure handling,
missing-Paystack-handle handling, role gating, empty-reason rejection,
non-active-tenant guard).

**Frontend** (Next.js/TypeScript/Tailwind) — login/register, Home dashboard
(connection/analysis/artifact counts and recent activity, pure client-side
composition of existing endpoints — no new backend surface), Ask screen
with live step trace, anomaly panel with drill-down chart, evidence panel,
report/presentation/export/email action bar, a Risks screen for on-demand
scans across every authorized table, a Documents screen for uploading/
previewing/deleting PDF/DOCX/XLSX/PPTX/CSV files with an inline attach-to-question picker
on Ask, Data Sources screen with per-connection table- and column-policy
editor (admin only), Team screen for setting per-user row-level access
scope (admin only), Billing screen (subscribe/cancel, refund-window
status), a Support screen for filing/viewing tickets, Analyses history
(reopen any past question, star one to keep it in a Saved filter) and a Library of generated reports/
presentations/exports, Audit log screen with a one-click hash-chain
verification check, a Security screen for two-factor setup/disable and
(admin only) the org-wide MFA policy. Separately, `/platform/*` is Meridian's own internal
admin panel — its own login, own nav, own session storage key — for
managing tenants, answering support tickets across every organization, and
maintaining the status page; see "Internal admin panel" above.

## What's NOT built, and why

| Gap | Why |
|---|---|
| Oracle/BigQuery/Databricks connectors | No test infrastructure for them in this environment; interface is ready (Snowflake is now built — see the Connectors section above) |
| Real OAuth/SSO (Google/Microsoft/Salesforce/SAP/etc.) | Needs a registered app with each provider — can't create that here |
| Automatic re-encryption when switching KMS backends | Existing credentials stay encrypted with whichever backend wrote them; migrating a live database needs a one-off script that runs both backends at once — see `docs/CLOUD_KMS.md` §4 |
| Multi-region uptime probing / alerting | Automated single-region probing now exists (see "Automated uptime monitoring" below) - it opens/resolves real incidents on its own, but doesn't check from multiple regions and doesn't alert anyone (email/SMS/Slack); pair with a real third-party monitor for those specifically |
| Pre-execution query cost estimation | Per-query cost is bounded by row LIMIT + timeout, not estimated before running. (Shared cross-process rate limiting/caching is no longer a gap — see the Redis section above, opt-in via `REDIS_URL`.) |
| Prescriptive analytics ("what should we do about it") | Not built — deliberately, see the Forecasting section above for why |
| Real lawyer review of `/privacy` and `/terms` | The pages exist and accurately describe what the software actually does (see "Legal pages" below), but they were written by inspecting the codebase, not by a lawyer — both pages say so plainly at the top. Get real legal review before relying on them for actual liability protection or NDPR/GDPR compliance. |
| Event-level product analytics (PostHog/Mixpanel/similar) | A first-party business-metrics dashboard now exists (see "Product analytics" above) - signups/questions per day, an activation funnel, tenant/plan/artifact breakdowns. What's still missing is per-event, per-screen tracking (which button someone clicked, where they dropped off within a single session, session replay) - that needs a real product-analytics tool, deliberately not wired in yet since it would mean sending user behavioral data to a new third-party sub-processor. |
| Real PDF table structure detection | XLSX/DOCX/PPTX uploaded as document-only analysis sources now get their real tables parsed as structured data and run through genuine computation (see "Structured-table document analysis" above). PDF deliberately doesn't - reliable table detection there needs actual layout analysis (a new dependency, e.g. `pdfplumber`/`camelot`) and is genuinely unreliable on a visually laid-out page; misreading two adjacent columns as one would silently produce a wrong computed number, worse than the existing honest text-extraction fallback. A PDF still gets full document-only analysis, just not this specific upgrade. |
| Malware scanning always-on | The structural upload checks (real file-type, password-protection, zip-bomb ratios - see "Locked and unsafe file detection" above) always run. A real signature scan is now available too but **opt-in**: `MALWARE_SCAN_PROVIDER=clamav` points `app/security/malware_scan.py` at a ClamAV daemon over its INSTREAM protocol (stdlib socket, no vendor SDK), off by default so it needs no extra infrastructure until you want it. Fail-closed (a `clamd` outage refuses uploads) unless `MALWARE_SCAN_FAIL_OPEN=true`. Verified end-to-end with a stub `clamd` (`tests/verify_malware_scan.py`, 8 checks). See `docs/MALWARE_SCANNING.md`. What's still not built: re-scanning on download, and sandbox detonation. |

## Running it

### 1. Backend

Requires **Python 3.11-3.13**. On a brand-new Python (3.14 at the time of
writing), several pinned native-extension dependencies
(`numpy`, `pandas`→numpy, `psycopg2-binary`, `pymssql`, and `pydantic`'s
`pydantic-core`) have no prebuilt wheel yet — pip silently falls back to
building from source, which needs a C compiler and, for `psycopg2-binary`,
PostgreSQL headers neither of which are set up by default, and it just
hangs rather than failing loudly. If you hit that: either install Python
3.12 for this project's venv, or bump those five pins to whatever
`pip install --dry-run <pkg>` resolves to a `cp<your-version>` wheel for on
your machine — that's exactly how the pins in this file were fixed.

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# put that key in .env as APP_SECRET_KEY (it also signs JWTs -- see the
# comment in app/security/auth.py if you want to split that into a
# separate secret for production)
# add your ANTHROPIC_API_KEY -- used only for SQL generation, follow-up
# resolution, and insight explanation; it never receives credentials or
# raw unaggregated tables

uvicorn app.main:app --reload --port 8000
```

### 2. Set up a read-only role on the database you want to connect

**Postgres:**
```sql
CREATE ROLE analytics_readonly LOGIN PASSWORD 'a-real-password';
GRANT CONNECT ON DATABASE your_db TO analytics_readonly;
GRANT USAGE ON SCHEMA public TO analytics_readonly;
GRANT SELECT ON your_table TO analytics_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analytics_readonly;
```

**MySQL/MariaDB:**
```sql
CREATE USER 'analytics_readonly'@'%' IDENTIFIED BY 'a-real-password';
GRANT SELECT ON your_db.* TO 'analytics_readonly'@'%';
FLUSH PRIVILEGES;
```

**SQL Server:**
```sql
CREATE LOGIN analytics_readonly WITH PASSWORD = 'a-real-password';
CREATE USER analytics_readonly FOR LOGIN analytics_readonly;
ALTER ROLE db_datareader ADD MEMBER analytics_readonly;
```
This one matters more than for Postgres/MySQL — SQL Server has no
session-level read-only transaction mode, so the connector's read-only
guarantee rests entirely on this role having no write grants. See the
caveat in `app/connectors/mssql.py`.

**Snowflake:**
```sql
CREATE ROLE analytics_readonly;
GRANT USAGE ON WAREHOUSE your_warehouse TO ROLE analytics_readonly;
GRANT USAGE ON DATABASE your_db TO ROLE analytics_readonly;
GRANT USAGE ON SCHEMA your_db.your_schema TO ROLE analytics_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA your_db.your_schema TO ROLE analytics_readonly;
GRANT SELECT ON FUTURE TABLES IN SCHEMA your_db.your_schema TO ROLE analytics_readonly;
CREATE USER analytics_readonly PASSWORD = 'a-real-password' DEFAULT_ROLE = analytics_readonly;
GRANT ROLE analytics_readonly TO USER analytics_readonly;
```
This matters even more than for SQL Server: Snowflake has no read-only
transaction mode *at all*, so unlike every other connector here there's
no independent, universal backstop behind this role's own grants — see
the caveat in `app/connectors/snowflake.py`. When connecting, the
warehouse name above goes in the "Warehouse" field on Data sources (not
in the account identifier or database field).

The app double-checks this at connection time regardless of your GRANTs —
see `verify_read_only()` in each connector.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE, defaults to localhost:8000
npm run dev
```

Open http://localhost:3000 — **Create account** registers you as the admin
of a new company workspace, then go to **Data sources** to connect your
database and **Ask** a question.

### 4. Internal admin panel (optional, for your own team)

`/platform/login` is a completely separate app surface — see the "Internal
admin panel" section below. First visit → "First-time setup" creates the
one and only "owner" account; that path then closes itself (a second
attempt is rejected). No signup form is ever shown for this anywhere else
in the app on purpose.

### 5. Tests / CI

`backend/tests/` holds one standalone check per security fix (real SQLite
DB + real FastAPI `TestClient`, DB layer never mocked — see
`backend/tests/README.md`). Run them all:

```bash
cd backend && python tests/run_regressions.py
```

`.github/workflows/ci.yml` runs that suite (17 checks) plus an
import/route smoke test, `pip-audit` (blocking — `pip-audit -r
backend/requirements.txt` reports **no known vulnerabilities**), the
frontend `build` and `lint` (both blocking — the `eslint-config-next` 16
`react-hooks` backlog is cleared, mostly by moving session reads onto a
`useSyncExternalStore` hook, `lib/useSession.ts`), and `npm audit`
(advisory), on every PR; Dependabot (`.github/dependabot.yml`) opens
weekly dependency PRs. The FastAPI / Starlette line is on 0.141 / 1.x
(`@app.on_event` → the `lifespan` context manager in `app/main.py`).

This app runs no in-process scheduler by design. Automated uptime
monitoring (`docs/UPTIME_MONITORING.md`) therefore needs an external timer
(a script + a shared-secret endpoint). The subscription-renewal reminder
(`docs/SUBSCRIPTION_REMINDERS.md`) does not — it computes on read off the
notification-bell poll — but ships a GitHub Action / cron script anyway for
teams that want the timing guaranteed regardless of who's logged in.

Other operational scripts in `backend/scripts/`: `paystack_plans.py`
(create/verify the three subscription plans on a Paystack account —
`docs/BILLING_GO_LIVE.md`) and `migrate_metadata_db.py` (SQLite → Postgres
metadata-store migration with per-table and audit-hash-chain verification —
`docs/POSTGRES_MIGRATION.md`).

## Architecture

```
question
  -> resolve follow-up context (if continuing a conversation)
  -> Schema Discovery (policy-filtered)
  -> Query Generator (LLM, SQL-only output)
  -> Query Validator (single SELECT, no mutation keywords, no stacking)
  -> Connector (BEGIN/START TRANSACTION READ ONLY, statement timeout)
  -> Output Guard (column allowlist, raw-row ceiling)
  -> Row-scope check (per-user data policy)
  -> Data Quality Agent (deterministic)
  -> Analytics Engine (deterministic -- sums, growth rates, grouping)
  -> Anomaly Detection (deterministic z-score + missing-data check)
  -> Investigation Agent (drills the top anomaly down one more dimension)
  -> Insight Agent (LLM interprets the already-computed numbers)
  -> saved as a QueryRecord + Conversation context updated
  -> streamed to the frontend as progress + a final evidence-backed answer
  -> optionally: report / presentation / export / email, from the same
     saved snapshot
```

Every step is audit-logged, including rejections, with the reason.
