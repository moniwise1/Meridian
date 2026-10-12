# General analysis delivery — 12 October 2026

Meridian analyses general data: operations, customers, inventory, research, sales
and finance. Individuals and business accounts share Ask; the financial/business
views are additional business features.

## Delivered

- Upload up to five files inside Ask. The first becomes the source, with the rest
  attached as supporting files. A question can reference at most ten documents.
- New TSV, JSON, text and Markdown support alongside Excel, CSV, PDF, Word and
  PowerPoint. Unsupported binaries are rejected. Text supports UTF-8 and UTF-16.
- Real numerical analysis of flat JSON record arrays and TSV, bounded to 50,000
  rows and 120 columns. Duplicate JSON keys and non-finite constants are rejected.
  Nested JSON is read as text, never guessed into a numerical table. Extraction
  retains a 50,000-character ceiling and 500-row JSON/TSV text previews.
  Multiple-file analysis uses bounded text; it does not claim full joined tables.
- Ten bounded prior document question/answer exchanges, with sticky group/value
  columns unless the next question names replacements. Prior answers are context,
  never evidence: each question rereads the source. Tenant/user/capability/row
  boundaries remain enforced. No general document Ask for row-restricted users.
- Business admins can deliberately publish source-specific company definitions.
  Personal notes and all analysis results remain private. Definitions guide the
  explanation and cannot replace real numerical calculations or grant data access.
- Admins can save twenty company reporting views: source, mappings, grouping,
  filters and dates. Saving validates the real source. Loading/recalculating uses
  the current reader's permissions, never the creator's data scope.
- Owner error-count drill-down and subscription-email team/support wording from
  older PRs. Conversation memory is adapted to the current v2 engine.

## Dashboard presentation

The individual, business and owner workspaces follow the supplied dashboard
reference: dark sidebar, compact metric cards, greeting banner, top bar, grouped
charts/lists and contextual Ask panels. Existing teal/mint/gold colours remain.
Every card/chart uses actual returned data, with unavailable figures shown as
unavailable rather than sample revenue, savings, profit or cash flow. Individual
workspaces remain general analysis workspaces. Business calculations, filtering,
drill-downs and source permissions remain intact. The owner dashboard retains its
platform-only metrics and owner-only Ask access.

Ask launchers use a per-user session-storage draft instead of putting private
questions in URLs. Advertising pixels are limited to hydrated signed-out marketing
pages, with automatic event configuration disabled and consent revoked elsewhere.
The responsive sidebar, profile links, notification bell and navigation remain
functional; no mock navigation/filter/report-generation control is introduced.

## Connections

All four database connector URLs use SQLAlchemy URL objects to preserve reserved
characters in credentials. New PostgreSQL/MySQL connections require certificate-
and hostname-verified TLS using the system trust store. Legacy transport settings
remain unchanged until an admin uses **Verify TLS**; a failed upgrade preserves
the old settings. SQL Server TLS is not added here; configure secure transport
with the server/driver. Snowflake retains provider TLS behavior.

Credentials remain encrypted in metadata. Private/loopback hosts are rejected;
source table/column and user row policies apply before query execution.

Read-only verification now inspects privileges rather than sending temporary-table
write probes. PostgreSQL checks read-only status and effective elevated/schema/
table/column grants. MySQL accepts explicit SELECT/SHOW VIEW/USAGE grants and fails
closed for ambiguous role grants. SQL Server checks database/object grants.
Snowflake disables secondary roles and inspects the active/inherited/PUBLIC role
grants with a bounded traversal, rejecting writes, ownership and grant options.
Metadata errors fail closed. Live server-specific certificate/grant compatibility
still requires a real connector round-trip; mocked driver tests do not prove it.

## Scheduled analyses, PDFs and alerts

Each user can configure twenty private daily/weekly schedules for files/databases.
Each run checks the current subscription, capabilities, source policy, row scope
and monthly question allowance. Optional PDFs use the existing report capability
and document allowance. Notifications and reports stay private. No scheduled
email is sent to external recipients.

Alerts use an exact computed metric label and a finite above/below threshold.
Only threshold crossings notify; missing/unverified metrics never trigger alerts.
Times are stored in UTC and shown in the device timezone. Recurrence is a fixed
24-hour/7-day interval, not a daylight-saving-aware local-time rule. Missed
intervals produce one fresh analysis, not a burst of paid catch-up requests.
An atomic claim advances the next interval before external work, preventing
duplicate claims; crashed/failed runs are not retried during the same interval.
Pause/remove does not cancel an already-started query/model request.

Notification polling and **Check due analyses** trigger the current user's jobs
while they use the app. Guaranteed offline runs need Railway configuration:

1. Set a strong backend `ANALYSIS_SCHEDULE_SECRET`.
2. Configure a Railway cron service every five minutes to call
   `POST /schedules/run-due`, passing that value in `X-Schedule-Secret`.
   Supply secrets from the cron environment, never tracked files, URLs or logs.
3. Each sweep handles at most ten due jobs. Monitor blocked/failed runs and service
   capacity. Real model calls and PDFs consume the user's plan allowances.

An unconfigured global runner returns 503; a wrong secret returns 401.
Without this configuration, offline runs are not guaranteed.

## Release and limits

Boot adds metadata tables `shared_source_definitions`,
`business_view_configurations` and `analysis_schedules`. Existing notes are not
made public, source rows are not edited, and existing columns are not removed.
Deploy both services from the same commit. Preserve signing/KMS/billing variables
and the existing correct `NEXT_PUBLIC_API_BASE` build variable. Existing plans
and payment mode are unchanged.

Full classified financial statements, budgets and receivables remain subsequent
work. Shared definitions do not establish missing accounting inputs or turn
revenue less mapped expenses into certified net profit. The new executive views
still use uploaded flat tables; connected databases are analysed through Ask.
The apex domain and cron configuration require an authenticated Railway session,
which was unavailable during this delivery.

Validation uses the full backend regression runner, frontend production build/
TypeScript and lint. General-analysis tests use real SQLite metadata, real source
files, real service metrics, real PDF generation, permission boundaries, schedule
claims and alert crossings. Model/driver boundaries are mocked; no real customer
DB, charge, model call or scheduled email is used.

Rollback: redeploy the preceding frontend/backend commit. New metadata tables
may remain unused. Review connector settings before rollback, which restores
weaker checks; prefer a forward fix for security-sensitive regressions.
