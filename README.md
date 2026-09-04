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
and only "owner" account via an unauthenticated `/platform/bootstrap` call
that permanently disables itself the moment one exists; every account
after that requires an existing owner to create it.

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
- Real registration/login: PBKDF2-SHA256 password hashing, signed JWT
  sessions. Every route derives `tenant_id`/`user_id` from the verified
  token — never from the request body — so a client can't claim a wider
  scope than it was granted.
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
  guessing at login is rate-limited the same way password guessing
  already is (a third `login_cooldown.py` guard, keyed by user id).
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
  and reproduced fixed against the same live server before shipping. NOT
  built: self-service recovery for a lost authenticator device — an admin
  removing and re-adding the account is currently the only way back in,
  same "no email-sending identity to build a real recovery flow on top
  of" gap as the rest of this app's account recovery.
- **Idle sign-out**: independent of the session token's own (much longer)
  expiry, 10 minutes with no mouse/keyboard/scroll activity shows an "Are
  you still here?" prompt; one more minute unanswered signs out and
  requires signing back in (`components/InactivityWatcher.tsx`, mounted
  in `AuthGate` for the tenant app only — not `/platform`, which has its
  own separate session entirely). Deliberately no fixed absolute session
  cap — activity alone keeps a session usable, only inactivity ever ends
  one early.
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

**Connectors**
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
reading-order text, OCR'd or native). Bounded to 20MB per upload and
50,000 extracted characters.
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
  recipient requires explicit confirmation. Ships a `ConsoleEmailBackend`
  that logs instead of sending — there's no real SMTP relay available here;
  swapping in SES/Postmark/SMTP means implementing one `EmailBackend.send`
  method.

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
generation, tenant-scoped, queryable via `/audit`. Hash-chained
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

**Frontend** (Next.js/TypeScript/Tailwind) — login/register, Home dashboard
(connection/analysis/artifact counts and recent activity, pure client-side
composition of existing endpoints — no new backend surface), Ask screen
with live step trace, anomaly panel with drill-down chart, evidence panel,
report/presentation/export/email action bar, a Risks screen for on-demand
scans across every authorized table, a Documents screen for uploading/
previewing/deleting PDFs/DOCX/XLSX with an inline attach-to-question picker
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
| Real SMTP/email provider | Console backend stands in; swap-in point is documented above |
| Automatic re-encryption when switching KMS backends | Existing credentials stay encrypted with whichever backend wrote them; migrating a live database needs a one-off script that runs both backends at once — see `docs/CLOUD_KMS.md` §4 |
| Automated multi-region uptime probing / alerting | The internal status page is manually-logged incidents, same convention as most SaaS status pages; pair with a real monitoring tool for actual automated probing |
| Pre-execution query cost estimation | Per-query cost is bounded by row LIMIT + timeout, not estimated before running. (Shared cross-process rate limiting/caching is no longer a gap — see the Redis section above, opt-in via `REDIS_URL`.) |
| Prescriptive analytics ("what should we do about it") | Not built — deliberately, see the Forecasting section above for why |
| Real invite-by-email | No SMTP identity to build a real invite link on |

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
