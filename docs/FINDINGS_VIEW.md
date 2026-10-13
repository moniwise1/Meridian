# Findings view and question-specific evidence

The findings view leads with the answer, its scoped measures, comparison or
trend charts, and source references. A figure's “Inspect calculation” control
shows its operation, numerator/denominator, exact filters, matched and parsed
row counts, exclusions, result and source version. Group charts have an
expandable values table with record counts. Missing values remain unavailable;
negative bars use a zero baseline and line charts break at missing values.
Displayed figures are rounded; the calculation reference retains the original
result. Findings based on model prose remain labelled as interpretations.

Verified table-tool calculations now enter the versioned analysis contract,
instead of displaying unrelated whole-file profile metrics as the primary
answer. Tool table IDs map to selected document order, including unparsed files;
filename-only source matching is not used because filenames can repeat.
Files remain independent, and calculations retain separate filter scopes.

The current conversation's follow-up actions use the existing Ask pipeline and
its source/authorization checks. Historical turns cannot submit follow-ups into
a newer thread. Detailed legacy result panels remain available in a collapsible
section. Old saved analyses still render through the legacy result path; this
release does not rewrite previously persisted snapshots.

PDF reports carry scoped metric units, computed group charts, grouped values,
source versions and the calculation audit. Missing values are never plotted as
zero. Reports distinguish deterministic measurements from extracted claims or
model interpretations and do not state that every number was independently
computed.

Validation includes real TableWorkspace calculations, duplicate source
filenames, contract reference validation, and reopening the generated PDF to
check units, filters, row counts and page bounds. PDF layout is reviewed by
rendering every fixture page. Build/lint checks are separate from signed-in
browser verification; do not claim the latter without an actual session.
