# The Ask analyst workspace

Ask now returns a versioned **analyst brief** alongside the result payload it
always returned, and the Ask page gained a per-source workspace: confirmed
business definitions, saved conversations, and background checks on uploaded
files.

Everything here is **additive**. Old saved analyses render exactly as they did
(they have no `analysis` object, and every existing panel still renders for
the ones that do). The brief is drawn above the existing panels, not instead
of them — the bar and pie charts, key findings, anomaly list, forecast panel,
export buttons and SQL viewer are untouched.

## What a user sees

**Business definitions and corrections.** Type a definition ("for us, revenue
excludes refunds and tax") and save it. Later questions on that source get it
as reference data. Nothing is inferred and stored on its own — only what the
user explicitly saves is remembered, and removing a note is immediate.

**Saved conversations.** Every completed analysis now belongs to a
conversation, including document-only ones, which previously could not be
followed up at all. Reopening one restores its turns; a follow-up continues
the thread and is always recomputed, never served from cache.

**Upload findings.** An uploaded file gets a background numeric check — missing
values, repeated rows, and the anomalies the existing detector finds. The
result appears in the workspace without the user asking a question, and can be
marked Reviewed, Expected, or Dismissed.

## The analysis contract

`backend/app/agents/analyst_contract.py` is authoritative;
`docs/ask-analysis.schema.json` is generated from it and
`frontend/lib/analyst.ts` mirrors it. `schema_version` is `"1.0"`.

The point of the contract is that **code assembles every number and every
provenance claim, never the model**:

- `build_analysis()` reads the already-computed snapshot. The model's prose
  becomes a `finding` with `kind: "hypothesis"`, never a measured value.
- A missing or non-finite number stays `null`. It is never rendered as `0`.
- `method` is `"computed"` only when a real table was parsed and aggregated.
  A figure read out of document text is `"extracted_text"` and the brief says
  so.
- Charts must reference a real table id and a numeric column, table rows must
  match their declared columns, and every metric/table/finding must reference
  evidence that exists. A brief that fails any of these raises rather than
  rendering.
- A percent-like value column ("rate", "ratio", "margin", "conversion", "%")
  gets no "Sum of" metric — summing percentages is meaningless.
- Confidence is split in two. `measurement` is about the arithmetic;
  `explanation` is about the causal story. They are frequently different, and
  the old single badge could not say that.

## Data layer

Startup creates `ask_memories`, `ask_findings` and `ask_scan_jobs`, and adds a
nullable `uploaded_documents.content_sha256` through the existing
`_ADDED_COLUMNS` mechanism in `backend/app/db/session.py` (there is no Alembic
in this project). New uploads get a SHA-256 content version, so a finding or an
analysis can say *which version of the file* it describes. Documents uploaded
before this shipped fall back to their document id.

## Access rules

- Memory, findings and workspace conversations are scoped to tenant **and**
  user **and** source. A teammate on the same tenant does not see them.
- Source access is re-checked when a conversation is reopened, not only when it
  was created — a revoked `document_retrieval` capability blocks it.
- A database conversation stores a fingerprint of the connection's table
  allowlist, column policy and the user's row scope. If any of those change,
  continuing that conversation is refused and a new one has to be started,
  rather than letting context built under wider access steer a later answer.
- The `authorize_source` check in `routes_analyst.py` runs on every endpoint,
  including for each document id carried by a conversation being reopened.

## Background checks

Upload checks are durable rows, not in-process tasks. Each invocation takes at
most three jobs, each job gets at most three attempts, jobs are claimed with a
conditional UPDATE so two concurrent requests cannot do the same work twice,
and a job stuck in `running` for 15 minutes becomes retryable. Findings get
deterministic SHA-based ids so a retry cannot duplicate them. The runner opens
its own session — a request-scoped session must never escape into a background
task. **No paid model calls happen in a check.**

## Deliberate first-release limits

- This describes an **uploaded snapshot**. It is not live monitoring, a
  scheduler, cross-upload change detection, or an alerting service. The prompt
  rules forbid the model from implying otherwise.
- Notes belong to one user and one source. They do not migrate to a replacement
  upload and are not organization-wide definitions.
- A document profile describes the parsed worksheet the existing heuristic
  picked. It does not apply arbitrary filters from the question, and the brief
  says so in its limitations rather than implying the filter was applied.
- Measurement confidence is capped at `medium`. Completeness does not prove
  currency consistency, correct metric definitions, or a complete reporting
  period.
- Database cache hits are still recent snapshots. A question with saved notes,
  or a resumed clarification, bypasses the cache entirely.

## Validation

From `backend`:

```bash
python tests/run_regressions.py
```

`tests/verify_analyst_workspace.py` is the check for this feature (the project
uses standalone `verify_*.py` scripts, not pytest — see `tests/README.md`). It
runs against a real SQLite database and the real route handlers and
`run_analysis()` generator, stubbing only the Anthropic calls. It covers the
contract's unknown/NaN handling, chart and evidence reference validation, the
no-sum-of-percentages rule, private memory, capability revocation, the
policy-signature refusal, dedupe/persistence/retry-capping of upload checks, a
real document follow-up computing a real total from a real CSV, the repeatable
additive migration, and the PDF/PPTX exports keeping both the new uncertainty
sections and the pre-existing deck content.

From `frontend`: `npx tsc --noEmit`, `npm run lint`, `npm run build`.
