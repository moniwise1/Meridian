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

**Auth & multi-tenancy**
- Real registration/login: PBKDF2-SHA256 password hashing, signed JWT
  sessions. Every route derives `tenant_id`/`user_id` from the verified
  token — never from the request body — so a client can't claim a wider
  scope than it was granted.
- Role-based access (`admin` can connect data sources and edit policy;
  other roles can't) and per-user capabilities (querying, report
  generation, email delivery, etc. can each be individually enabled).

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
- Connector interface (`app/connectors/base.py`) is small enough that
  adding Oracle/Snowflake/BigQuery/etc. means implementing 4 methods, not a
  redesign — not built in this slice, since I can't test them without real
  instances.

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
`/documents`) — upload a PDF, DOCX, or XLSX; text (and table cell content)
is extracted once at upload time and can be attached to a question on Ask,
where it's referenced alongside the database analysis. This is the first
genuinely externally-authored content anywhere in this app's LLM calls —
schema field names and row values come from a database the tenant already
connected and authorized, but a document could contain anything, including
text written to look like instructions. Handled with the same discipline:
extracted text is always passed to the LLM as a labelled, untrusted
`reference_documents` payload (see `insight_agent.py`), never blended into
instruction text, and the model is explicitly told not to comply with
anything inside it that looks like an instruction. Attaching a document
also opts a question out of the result cache (see Query result cache above)
and out of follow-up chaining, rather than trying to fold document identity
into either of those correctly. NOT built: OCR (a scanned PDF's text
extracts to nothing, silently — surfaced honestly as an empty result, not
pretended to work) or real PDF table structure (flattened to reading-order
text). Bounded to 20MB per upload and 50,000 extracted characters.
Extraction verified against real generated PDF/DOCX/XLSX files (not
reimplemented logic) — actual page text, paragraphs, tables, multi-sheet
content, truncation at the character cap, and graceful (non-crashing)
handling of a corrupt file all confirmed. The whole feature was then
verified with a real HTTP round trip through the live FastAPI app against
a real SQLite database (register → upload → list → get → permission-denied
delete by a non-uploader → admin delete), and separately, cross-tenant
document access was confirmed blocked both at the API layer (404) and at
the exact DB query `planner.py` uses to resolve `document_ids` — the one
place a wrong tenant filter here would have mattered.

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

**Rate & concurrency limits** (`app/security/rate_limit.py`) — `/ask/stream`
is the one endpoint that costs a real LLM call plus a live customer-DB
query per request, so it's rate-limited per user (sliding window,
`ASK_RATE_LIMIT_PER_USER_PER_MINUTE`, default 10/min) and concurrency-capped
per tenant (`ASK_MAX_CONCURRENT_PER_TENANT`, default 3 at once). This
complements, not duplicates, the per-query bounds that already existed:
`query_validator.py` injects a `LIMIT` into every generated query and each
connector enforces `QUERY_TIMEOUT_SECONDS` — those cap the cost of *one*
query, this caps *how many* run. Honest limitation: state is in-process
(a dict guarded by a lock), not shared across worker processes — behind
multiple workers the effective limit is (configured limit × worker count),
not the configured number. A real multi-process deployment needs a shared
store (Redis, or the metadata DB) for a genuine global limit.

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
anchored outside this database entirely; not implemented here. Full
caveats, including a known race on concurrent writers, are in the
module docstring.

**Frontend** (Next.js/TypeScript/Tailwind) — login/register, Home dashboard
(connection/analysis/artifact counts and recent activity, pure client-side
composition of existing endpoints — no new backend surface), Ask screen
with live step trace, anomaly panel with drill-down chart, evidence panel,
report/presentation/export/email action bar, a Risks screen for on-demand
scans across every authorized table, a Documents screen for uploading/
previewing/deleting PDFs/DOCX/XLSX with an inline attach-to-question picker
on Ask, Data Sources screen with per-connection table- and column-policy
editor (admin only), Team screen for setting per-user row-level access
scope (admin only), Analyses history (reopen any past question) and a
Library of generated reports/presentations/exports, Audit log screen with
a one-click hash-chain verification check.

## What's NOT built, and why

| Gap | Why |
|---|---|
| Oracle/Snowflake/BigQuery/Databricks connectors | No test infrastructure for them in this environment; interface is ready |
| Real OAuth/SSO (Google/Microsoft/Salesforce/SAP/etc.) | Needs a registered app with each provider — can't create that here |
| Document OCR / scanned-PDF text extraction | pypdf only reads an embedded text layer; a scanned document extracts to nothing, honestly, rather than pretending to work — see the Document intelligence section above |
| Real SMTP/email provider | Console backend stands in; swap-in point is documented above |
| Cloud KMS for credential encryption | Uses a local Fernet key (`.env`); documented as the production gap |
| Shared (cross-process) rate limiting / caching, pre-execution query cost estimation | Rate/concurrency limits and the result cache exist but are in-process only (see above); per-query cost is bounded by row LIMIT + timeout, not estimated before running |
| Saved Work (manual bookmarking) | Not built — Analyses/Library cover browsing all past work, but there's no way to pin/save specific items |
| Prescriptive analytics ("what should we do about it") | Not built — deliberately, see the Forecasting section above for why |
| Real invite-by-email | No SMTP identity to build a real invite link on |
| Externally-anchored (fully tamper-*proof*) audit trail | Audit log is hash-chained and self-verifying now, but the chain's head hash isn't anchored outside this database — see the audit log section above |

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
