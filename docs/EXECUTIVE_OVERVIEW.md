# Executive Overview and Ask: first delivery

Baseline: main commit e4f6d9222fafb906da3d9ee43d58b77ae0f6442e.
Development branch: feat/business-overview-ask. Railway remains production;
this branch must not be merged/deployed without explicit release approval.

## Delivered

- `/overview`: business-only CSV/XLSX Executive Overview. The API independently
  checks normalized business account type (legacy NULL remains business), active
  subscription, querying/document capabilities, tenant ownership and row scope.
- Explicit date, revenue, expense and currency mapping; equal-length preceding
  period comparisons; exact decimal sums and two-decimal ROUND_HALF_UP display.
- Revenue chart with day drill-downs that preserve the period totals, daily
  performance, source filename/version/upload time, calculation time and original
  spreadsheet row numbers. Records shown are capped at 100 per requested slice;
  totals include all authorized period rows, never just that preview.
- Overview Ask answers supported revenue/expense questions from the exact same
  computation. Unsupported causes, accounting profit and forecasts are declined.
- Existing customer Ask (individual and business): starter questions, loading
  status, explicit independent-question/context toggle, stop-response control,
  question length limit and detection of prematurely ended streams.
- Mobile navigation collapses above the workspace; desktop retains its sidebar.
- `/platform/ask`: owner-only questions about signups, saved analysis usage,
  current subscription status and ticket backlog. Uses deterministic counts from
  platform metadata; never reads customer result snapshots, uploaded text or
  question contents. This is a bounded query workflow, not a general-purpose
  platform AI agent. Active status includes manual activations, not proven revenue.

## Data requirements and formulas

Use a flat table with one header row and at most 50,000 rows/120 columns.
XLSX sheet selection is explicit; CSV always reads its only table. Dates are
spreadsheet date values or ISO YYYY-MM-DD, interpreted as source calendar dates.
Ambiguous strings, missing dates, mixed/missing currencies and non-decimal
amounts are rejected. Numeric Excel date serials are not guessed. Confirm the
single source currency; map its currency column when available. Currency codes
must have three letters; no currency conversion or currency registry is supplied.

Revenue = sum of the explicitly mapped revenue column. Mapped expenses = sum
of the mapped expense column. Revenue less mapped expenses = their difference.
This difference does **not** establish gross/net accounting profit or cash flow.
Unmapped amounts, missing amount cells or a period with no rows yield unavailable
metrics rather than zero. Negative revenue amounts act as refunds; negative
expenses act as credits. Duplicate rows are blocked until explicitly confirmed
as legitimate; Meridian does not silently deduplicate financial transactions.

Date boundaries are inclusive. A 12-day selected period compares with the
immediately preceding 12 days. Change = (current − previous) / abs(previous) ×100;
a missing/zero previous total makes the percentage unavailable. Uploaded data
does not establish full-period coverage, so comparisons carry that limitation.
Row-scoped users see only matching rows; a missing scope column fails closed.
The original upload row index survives filtering and drill-downs.

## Ask authorization changes

SQLGlot is a justified new dependency: sqlparse/keyword checks cannot resolve
column lineage, aliases, CTEs or inject filters safely. Existing read-only SQL
validation and connector transaction controls remain in place. The new policy
checks base tables and columns against the authorized schema, removes default
sensitive columns, rejects unapproved anonymous functions and sequence writes,
injects parameterized row predicates **before aggregation**, and clamps the
outermost result limit using the connector's dialect (TOP for SQL Server).
Ask, automatic investigation and risk scans use this policy.

Complex queries that cannot be verified are rejected instead of executed.
Qualified database/schema references are intentionally unsupported in this
first policy version. Known database read-only probe and SQL Server timeout
limitations from the audit remain; use real SELECT-only database roles.
SQL syntax is covered in tests; live database connector round-trips remain a
release prerequisite. The main Ask engine still uses its existing generic
analytics heuristics; company-wide financial definitions are subsequent work.

History and generated artifacts are now private to the creating user. Old
tenant-wide sharing was unsafe for row-restricted colleagues. New snapshots
carry a policy signature; changed source permissions invalidate access. Legacy
database results with configured source restrictions must be rerun. Signed
downloads also check the creating user's current access before serving a file.
Existing report email policy still governs intentional outbound sharing.

Document Ask and raw-text retrieval are denied for row-restricted users because
text extraction cannot enforce their row filters. Such users can use an
authorized database or the scoped Executive Overview instead.

## Limits and subsequent deliveries

This is the first increment, not the entire BI roadmap. Mappings are request/view
configuration, not persisted company-wide metric definitions. Overview currently
uses uploaded flat tables, not connected databases. Financial statements,
budgets, receivables, shared saved configurations, accounting classifications,
workspace-wide AI integration, scheduled business reports and alerts remain
future deliveries in the approved product order. No fake KPIs fill those gaps.

Stopping a customer response aborts the browser stream; database/AI work already
started can still complete on the server. It is not guaranteed query cancellation.

## Validation and release

Run `cd backend && python tests/run_regressions.py` with requirements installed.
The runner sets PYTHONPATH and isolates each test in its own process. The new
`verify_executive_ask.py` tests known financial inputs, missing/mixed currencies,
refunds, date comparisons, original-row drill-downs, aggregate row isolation,
unauthorized columns/tables/functions, result caps, user/tenant boundaries,
changed permissions, signed downloads and owner authorization. Existing fixtures
now include real schema descriptions/source registrations, as production does.

Frontend checks: `npm ci`, `npm run build`, `npm run lint`, `npx tsc --noEmit`.
Dependency checks: `python -m pip_audit -r backend/requirements.txt`,
`npm audit --omit=dev --audit-level=high`, plus full advisory `npm audit`.
Next.js and eslint-config-next are patched together from 16.3.4 to 16.3.8.
Compatible transitive patches are reflected in package-lock.json.
The full npm audit still reports five high advisories in the development-only
braces/micromatch/fast-glob/Next ESLint dependency chain. Its suggested forced
remediation downgrades eslint-config-next to 14.x, which is incompatible with
this application's Next 16 conventions; that downgrade is intentionally not
applied. Production-only npm audit and backend pip audit are separate checks.

Automated browser visual testing could not run: the environment had no Chromium
and its browser download failed. Manually review desktop/mobile layouts and
interactive chart drill-downs before production release. No real Anthropic,
Paystack, cloud KMS or production database calls were exercised by this work.

No new environment variable or database migration is introduced. Existing boot
migrations still run when the backend starts; review deployed schema and backup
before any release. Build backend and frontend together on a separate Railway
staging service with synthetic data. Preserve existing secrets and billing mode.
Rebuild frontend with the correct staging NEXT_PUBLIC_API_BASE; validate business,
individual and owner sessions separately. Confirm live connector read-only roles,
limits and query compatibility before approving a production rollout.

Rollback: redeploy both services from baseline e4f6d92. No new tables or columns
need removal. New snapshots remain JSON-compatible with the previous application.
However rollback restores the previous weaker authorization behavior; prefer a
forward security fix or restrict affected features if rolling back for a UI issue.

## Observed delivery checks

- Backend regression runner: all 39 checks passed; the expanded Executive/Ask
  check also passed after its final CSV/XLSX, drill-down and access additions.
- Frontend build (including TypeScript) and lint passed after the chart changes.
- Backend dependency audit: no known vulnerabilities.
- Production-only npm audit: zero vulnerabilities after compatible lock updates.
- Full npm audit: five high development-chain advisories remain as described above.
- Browser visual/end-to-end check: blocked by unavailable Chromium download.

The pull request's latest CI run is the final check for the committed tree.
