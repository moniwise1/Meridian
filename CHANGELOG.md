## 2026-10-12 — General file/database analysis

Inline and multi-file Ask uploads; JSON/TSV/text/Markdown; grounded document conversation memory; shared company definitions and saved reporting views; private recurring analyses/PDFs and metric alerts; verified PostgreSQL/MySQL TLS for new registrations; credential URL escaping and grant inspection; owner error drill-down and subscription email improvements. See docs/GENERAL_ANALYSIS.md for rollout and limits.

# Changelog

## Unreleased — Executive Overview and Ask foundation

- Add explicitly mapped, business-only executive KPIs from CSV/Excel uploads,
  period comparisons, revenue chart drill-downs and source record inspection.
- Use one decimal calculation module for Overview and its supported Ask answers.
- Improve customer Ask source status, suggestions, context controls and response
  interruption; add owner-only platform operations Ask.
- Authorize generated SQL against table/column policies and bind row filters
  before aggregates in Ask, investigation and risk scans; apply dialect-aware caps.
- Make saved analyses/artifacts private and recheck current source permissions;
  fail closed on document text/Ask for row-restricted accounts.
- Patch Next.js/eslint-config-next to 16.3.8 and compatible transitive dependencies.
- Add regression coverage and deployment/rollback notes in EXECUTIVE_OVERVIEW.md.

Production release remains pending explicit approval.
