# Source-backed table investigation

Ask can now choose question-specific calculations over parsed files, including
when several documents are selected. A bounded `analyze_table` tool receives only
the tables already authorized and loaded for this analysis; it cannot fetch data,
run SQL, execute Python or join files.

Supported calculations: sum, average, median, minimum, maximum, row count and
weighted percentage rate (`100 * sum(numerator) / sum(denominator)`). It supports
one group column, ascending/descending ranking, and up to four exact text or
numeric comparison filters. For a rate, rows missing either operand are excluded
from both sums; zero denominators and negative operands return no rate. Never
average branch conversion percentages when the intended measure is overall
conversion—use the sales and footfall columns together.

Every successful calculation includes its file, filters, operation, row counts,
missing/non-finite exclusions and an evidence ID. Results are recorded in the
analysis snapshot and summarized in its data-quality notes. Group outputs are
limited to 50 with an explicit truncation indicator. Requests with more than
1,000 distinct groups are rejected with a request to narrow the scope. Each
analysis permits at most 12 successful table calculations inside the existing
six-turn model tool loop.

Tables are parsed independently, one best usable table per file. The existing
parser limits and supported file formats still apply. A workbook with many sheets
is not automatically analyzed in full; the selected parsed table is the scope.
Documents without a usable table still use extracted text and the bounded
transcribed-number calculator. Automatic joins, arbitrary code, date-range
interpretation and web research are not part of this tool. When an unresolved
definition, denominator or date range could change the answer, Ask is instructed
to ask a precise clarification rather than silently invent it.

Tests cover actual parsed JSON/CSV files through the planner and real SQLite
history persistence, known-answer calculations, missing values, unequal
denominators, per-file isolation, malformed input, tool budgets and the model/tool
roundtrip. Model calls are simulated in these tests: this verifies calculation
accuracy and integration, not that every live model will always select the best
tool or interpret a question correctly.
