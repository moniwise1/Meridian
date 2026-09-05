"""
Tabular Analysis - gives an uploaded document the SAME treatment a
connected database already gets (BUILD SPEC sections 10, 11, 14): real
tables, parsed as real structured data, run through the exact same
deterministic computation engines (analytics_engine.py, data_quality.py,
anomaly_detection.py) already trusted for SQL results - rather than
flattened to text and handed to the LLM to eyeball and do arithmetic on.

Why this exists: document_intelligence.py's extraction is text/table
FLATTENING, not comprehension - by design, per that module's own
docstring, it hands the LLM text "exactly the way it already reads
computed metrics." That's fine for a normal-sized table. It falls apart
for a genuinely large or wide spreadsheet: a real production example (a
retail scorecard with 5,232 columns) would blow through
MAX_EXTRACTED_CHARS within the first couple of flattened rows, handing
the LLM a near-meaningless fragment instead of the actual data - and even
for a table small enough to fit, asking an LLM to mentally group-by and
average a table it's reading as prose is asking it to do arithmetic this
app's own core principle says it should never be trusted to do (see
analytics_engine.py's docstring). This module is the fix: parse the
document's REAL table(s) into a real pandas DataFrame, compute real
breakdowns/trends/quality-checks with the same code the database path
uses, and only then hand the LLM already-computed numbers to narrate -
exactly the SQL-generate -> execute -> analytics_engine -> explain()
pipeline in planner.py, with "parse a real table" standing in for
"execute a real query."

Scope, and why it stops where it does:
- XLSX: a real spreadsheet's own sheet(s), read with pandas/openpyxl -
  the most natural fit, since a spreadsheet already IS tabular data.
- DOCX/PPTX: python-docx/python-pptx already expose an embedded table's
  real cells directly (table.rows -> row.cells, or shape.table) - no
  guessing involved, so extracting those as a real DataFrame is exactly
  as safe as reading a spreadsheet.
- PDF: deliberately NOT attempted here. document_intelligence.py's own
  docstring already flags this as a known, accepted limitation: real PDF
  table structure detection needs actual layout analysis (a new
  dependency, e.g. pdfplumber/camelot) and is genuinely unreliable on a
  visually laid-out page - misreading two visually-adjacent columns as
  one, or vice versa, would silently produce a WRONG computed number,
  which is worse than this app's existing honest "read it as text and
  say so" fallback. A PDF still gets full document-only analysis; it
  just doesn't get the structured-computation upgrade this module adds
  for the other three formats.

Every function here is pure/deterministic pandas - no LLM call, no
network access, matching analytics_engine.py's own house rule.
"""
import datetime
import re
from dataclasses import dataclass, asdict

import docx
import pandas as pd
import pptx

from app.agents.analytics_engine import summarize
from app.agents.data_quality import assess
from app.agents.anomaly_detection import detect as detect_anomalies

# A table wider than this is treated as "not a flat table this module
# understands" rather than guessed at - the exact 5,232-column real-world
# case that motivated this module in the first place. Document-only
# analysis falls back to the existing text-extraction path for anything
# this rejects, not a crash or a wrong answer.
MAX_TABLE_COLUMNS = 120
MAX_UNNAMED_COLUMN_RATIO = 0.2  # pandas auto-names a blank/duplicate header "Unnamed: N"
MIN_TABLE_ROWS = 2
MAX_SHEETS_TRIED = 10
MAX_GROUP_COLUMNS = 5
MAX_VALUE_COLUMNS = 15
MAX_GROUP_CARDINALITY = 60
MAX_HEADER_SCAN_ROWS = 20  # how far down to look for a real header row that isn't row 0
MIN_REPEATING_BLOCK_MARKERS = 3  # fewer than this isn't real evidence of a repeating layout

_ID_LIKE_NAME = re.compile(r"\b(id|uuid|no|code|key|number|#)\b", re.IGNORECASE)
_GROUP_KEYWORDS = ("store", "region", "state", "agent", "branch", "product", "category",
                    "department", "shop", "outlet", "supervisor", "manager", "zone", "area")
_DATE_KEYWORDS = ("date", "month", "period", "week", "year", "day")
_PERCENT_LIKE_NAME = re.compile(r"score|percent|%|rate|achievement", re.IGNORECASE)


def _rejection_reason(df: pd.DataFrame) -> str | None:
    """None means usable. Otherwise, a specific, human-readable reason a
    real user can actually understand - this is surfaced verbatim in the
    Ask screen's step trace (see planner.py) so "why didn't this get the
    structured treatment" is never a mystery the user has to take on
    faith. The exact 5,232-column real-world case that motivated this
    module produces a reason naming the real count and the real limit,
    not a generic "couldn't parse it"."""
    if df is None or df.shape[1] < 2:
        return "fewer than 2 columns"
    if df.shape[0] < MIN_TABLE_ROWS:
        return f"only {df.shape[0]} data row(s) — need at least {MIN_TABLE_ROWS}"
    if df.shape[1] > MAX_TABLE_COLUMNS:
        return (f"{df.shape[1]:,} columns — over the {MAX_TABLE_COLUMNS}-column limit for automated "
                f"structured analysis, which suggests a complex multi-block layout (e.g. one set of "
                f"columns repeated per week/month) rather than a single flat table")
    unnamed = sum(1 for c in df.columns if str(c).startswith("Unnamed:") or str(c).strip() == "")
    if unnamed / df.shape[1] > MAX_UNNAMED_COLUMN_RATIO:
        return (f"{unnamed} of {df.shape[1]} columns have no real header text — the real header row is "
                f"likely offset from where this file's structure was expected, or spans multiple rows")
    numeric_cols = df.select_dtypes(include="number").columns
    coerced_numeric = sum(
        1 for c in df.columns if c not in numeric_cols and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.6
    )
    if len(numeric_cols) + coerced_numeric == 0:
        return "no column contains numeric data to compute anything from"
    return None


def _is_usable_table(df: pd.DataFrame) -> bool:
    return _rejection_reason(df) is None


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """DOCX/PPTX table cells are always strings (python-docx/pptx give
    plain text, unlike openpyxl which preserves a spreadsheet cell's real
    type) - this recovers real numeric dtype per column where the values
    actually look numeric, so summarize()/assess() below can treat them as
    numbers instead of silently skipping every column as non-numeric
    text. A column stays text if fewer than 60% of its values parse as a
    number, rather than coercing a mostly-text column into mostly-NaN."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            coerced = pd.to_numeric(
                out[col].astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
                errors="coerce",
            )
            if coerced.notna().mean() > 0.6:
                out[col] = coerced
    return out


def _find_header_row(raw: pd.DataFrame, max_scan: int = MAX_HEADER_SCAN_ROWS) -> int | None:
    """A real spreadsheet's header isn't always row 0 - a title row, a
    company logo cell, or a blank spacer row above it is common. Scans
    the first `max_scan` rows and scores each on how header-like it looks
    (mostly filled in, mostly distinct values, mostly text rather than
    numbers - numbers belong in DATA rows, not header rows), returning
    the best-scoring row rather than assuming row 0 is always right. This
    is what let a real production workbook's actual header (row 1, not
    row 0 - a blank spacer row sat above it) get found correctly instead
    of being read as 5,000+ meaningless "Unnamed: N" columns."""
    best_row, best_score = None, 0.0
    for i in range(min(max_scan, len(raw))):
        row = raw.iloc[i]
        non_null = row.notna().sum()
        if non_null < 2:
            continue
        text_like = sum(1 for v in row if isinstance(v, str) and v.strip())
        distinct = row.dropna().astype(str).nunique()
        score = non_null + text_like + distinct
        if score > best_score:
            best_score, best_row = score, i
    return best_row


def _find_repeating_block_markers(header: pd.Series) -> list[int]:
    """Header cells that are real datetime values, at 3+ positions - the
    exact shape a monthly/weekly tracker workbook produces (one identical
    block of metric columns repeated after each period's date marker,
    which is why the real production case behind this module had 5,232
    columns in the first place: ~12 real metrics x ~35 periods, laid out
    side by side rather than stacked). Fewer than
    MIN_REPEATING_BLOCK_MARKERS matches isn't treated as real evidence of
    this layout - a spreadsheet with one or two incidental date columns
    is just a normal table with a date column, not this pattern."""
    markers = [i for i, v in enumerate(header) if isinstance(v, (datetime.datetime, pd.Timestamp))]
    return markers if len(markers) >= MIN_REPEATING_BLOCK_MARKERS else []


def _reshape_repeating_blocks(raw: pd.DataFrame, header_row: int, markers: list[int]) -> pd.DataFrame:
    """Un-pivots a wide "one block of columns per period" sheet into a
    long, tidy table - one row per (identity, period) combination - the
    same transformation pandas' own `melt`/`wide_to_long` exist for,
    applied here based on the real date markers actually found in the
    header rather than a fixed/guessed column layout. Every value in the
    result is still a real cell read directly off the sheet; this only
    reshapes which axis a period lives on (columns -> rows), it never
    computes or estimates anything. The resulting table has id_columns +
    (one block's own column count) + 1 columns, typically small enough to
    pass the normal cleanliness check even when the original sheet, at
    5,000+ columns, could not."""
    header = raw.iloc[header_row]
    body = raw.iloc[header_row + 1:]
    id_cols = list(range(0, markers[0]))
    id_names = [str(header.iloc[c]).strip() if pd.notna(header.iloc[c]) else f"col_{c}" for c in id_cols]

    frames = []
    for block_i, start in enumerate(markers):
        end = markers[block_i + 1] if block_i + 1 < len(markers) else len(header)
        period_label = header.iloc[start]
        # The marker column itself (`start`) is not just a period label -
        # its own VALUES are real data too (a real production example:
        # the date-headed column's values were the agent's actual
        # composite score for that period, not metadata about the
        # period). Including it as "value" rather than discarding it is
        # what makes the reshape recover the actual metric the period
        # marker was reporting on, not just which period it was.
        block_header = header.iloc[start:end]
        block_names = [
            "value" if i == 0 else
            (str(v).strip() if pd.notna(v) and not isinstance(v, (datetime.datetime, pd.Timestamp))
             else f"metric_{start}_{i}")
            for i, v in enumerate(block_header)
        ]
        block_data = body.iloc[:, start:end].copy()
        block_data.columns = block_names
        # A block can itself contain a repeated sub-pattern (a real
        # production example: "Customers Served, Target, MTD Achievement,
        # 1st, 2nd, ... 31st" repeated once per product within the same
        # monthly block) - the spreadsheet gives no way to tell WHICH
        # product a later repeat of "Target"/"1st" belongs to beyond raw
        # column position, so keeping only the first occurrence of each
        # name recovers the real, meaningful once-per-block summary
        # metrics and drops the indistinguishable noise, rather than
        # inventing a suffix that implies a distinction the data doesn't
        # actually support.
        block_data = block_data.loc[:, ~block_data.columns.duplicated()]
        id_data = body.iloc[:, id_cols].copy()
        id_data.columns = id_names
        combined = pd.concat(
            [id_data.reset_index(drop=True), block_data.reset_index(drop=True)], axis=1,
        )
        combined.insert(len(id_names), "period", period_label)
        frames.append(combined)

    long_df = pd.concat(frames, ignore_index=True)
    # Rows with no real identity at all are unfilled template placeholder
    # rows (a real production example: a 347-row roster sheet where only
    # 67 rows actually had an agent name in them) - dropped here rather
    # than counted as real, empty data points. Filtered on the first
    # NON-ID-like identity column specifically, not just id_names[0]: a
    # real production example's own first identity column was a plain
    # sequential row number ("No" - 1, 2, 3, ...), which stays filled in
    # for every placeholder row too, so filtering on it wouldn't have
    # dropped a single blank row and would have silently let hundreds of
    # empty template rows drag down every average/trend computed next.
    filter_col = next((c for c in id_names if not _ID_LIKE_NAME.search(str(c))), None)
    if filter_col:
        long_df = long_df[long_df[filter_col].notna() & (long_df[filter_col].astype(str).str.strip() != "")]
    return _coerce_numeric_columns(long_df)


def _try_wide_block_reshape(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Second-tier attempt for a sheet that failed the simple flat-table
    read - specifically for the "too many columns" case, which is exactly
    what a repeating-block layout looks like before it's unpivoted. Only
    proceeds with real evidence (a found header row AND 3+ real date
    markers in it); returns None rather than guessing when that evidence
    isn't there, same as every other rejection path in this module."""
    header_row = _find_header_row(raw)
    if header_row is None:
        return None
    markers = _find_repeating_block_markers(raw.iloc[header_row])
    if not markers:
        return None
    return _reshape_repeating_blocks(raw, header_row, markers)


def _extract_xlsx_tables(file_path: str) -> tuple[list[pd.DataFrame], list[str]]:
    try:
        sheets = pd.read_excel(file_path, sheet_name=None, engine="openpyxl", header=None)
    except Exception as e:
        return [], [f"couldn't open this file as an XLSX workbook at all ({e})"]
    tables, diagnostics = [], []
    for name, raw in list(sheets.items())[:MAX_SHEETS_TRIED]:
        raw = raw.dropna(axis=1, how="all").dropna(axis=0, how="all")
        header_row = _find_header_row(raw)
        if header_row is None:
            diagnostics.append(f"sheet \"{name}\": no row looks like a real header (mostly text, mostly filled in)")
            continue
        # The raw column count is checked BEFORE any deduplication -
        # deduping first and checking the reduced count second would let
        # a genuinely too-wide repeating-block sheet (a real production
        # example: ~5,232 raw columns collapse to ~70 once every
        # duplicate metric name across all 12 months is deduped down to
        # its first occurrence) slip through as an ordinary "flat" table,
        # silently discarding 11 of its 12 real months' data rather than
        # reshaping them into rows the way _try_wide_block_reshape does.
        # A too-wide sheet always goes straight to the reshape attempt;
        # it never gets a naive flat-table interpretation at all.
        if raw.shape[1] - 1 > MAX_TABLE_COLUMNS:  # -1: header_row itself isn't a data column
            reshaped = _try_wide_block_reshape(raw)
            if reshaped is not None and _is_usable_table(reshaped):
                tables.append(reshaped)
            elif reshaped is not None:
                diagnostics.append(
                    f"sheet \"{name}\": found a repeating-block layout and reshaped it, but the result "
                    f"still isn't usable ({_rejection_reason(reshaped)})"
                )
            else:
                diagnostics.append(
                    f"sheet \"{name}\": {raw.shape[1] - 1:,} columns — over the {MAX_TABLE_COLUMNS}-column "
                    "limit, and no repeating date-block pattern was found to reshape it by either"
                )
            continue

        df = raw.iloc[header_row + 1:].copy()
        df.columns = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(raw.iloc[header_row])]
        # A header row can repeat the same text more than once even on a
        # normally-sized sheet (a title reused as a sub-heading, a blank
        # cell twice falling back to the same "col_N") - df[col] returns
        # a DataFrame instead of a Series for a duplicated label, which
        # breaks every per-column check below in a confusing way. Keeping
        # only the first occurrence of each name, same as the reshape
        # path already does for its own per-block duplicates. Safe to do
        # here specifically because the width check above already ruled
        # out the one case (a repeating-block sheet) where deduping
        # first would have hidden real data instead of just tidying up
        # incidental duplicate labels.
        df = df.loc[:, ~df.columns.duplicated()]
        # Reading with header=None (needed so _find_header_row can look
        # at row 0 itself) means pandas never got to apply its usual
        # header-excluded dtype inference - slicing the header text back
        # out of a column afterward leaves it typed as `object` even when
        # every remaining value is a real number. _coerce_numeric_columns
        # (already relied on for DOCX/PPTX, whose cells are always
        # strings to begin with) recovers real numeric dtype the same way
        # here.
        df = _coerce_numeric_columns(df)
        reason = _rejection_reason(df)
        if reason is None:
            tables.append(df)
        else:
            diagnostics.append(f"sheet \"{name}\": {reason}")
    return tables, diagnostics


def _table_from_docx_table(table) -> pd.DataFrame | None:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if len(rows) < MIN_TABLE_ROWS + 1:
        return None
    header, body = rows[0], rows[1:]
    if len(set(header)) != len(header):  # duplicate header cells (a merged-cell table) - not a clean flat table
        return None
    return pd.DataFrame(body, columns=header)


def _extract_docx_tables(file_path: str) -> tuple[list[pd.DataFrame], list[str]]:
    try:
        document = docx.Document(file_path)
    except Exception as e:
        return [], [f"couldn't open this file as a DOCX document at all ({e})"]
    if not document.tables:
        return [], ["this document has no tables at all — just paragraph text"]
    tables, diagnostics = [], []
    for i, table in enumerate(document.tables, start=1):
        df = _table_from_docx_table(table)
        if df is None:
            diagnostics.append(f"table {i}: too small, or its header row has duplicate/merged cells")
            continue
        df = _coerce_numeric_columns(df)
        reason = _rejection_reason(df)
        if reason is None:
            tables.append(df)
        else:
            diagnostics.append(f"table {i}: {reason}")
    return tables, diagnostics


def _extract_pptx_tables(file_path: str) -> tuple[list[pd.DataFrame], list[str]]:
    try:
        presentation = pptx.Presentation(file_path)
    except Exception as e:
        return [], [f"couldn't open this file as a PPTX presentation at all ({e})"]
    tables, diagnostics = [], []
    table_count = 0
    for slide_i, slide in enumerate(presentation.slides, start=1):
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            table_count += 1
            rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
            if len(rows) < MIN_TABLE_ROWS + 1:
                diagnostics.append(f"slide {slide_i}'s table: too few rows")
                continue
            header, body = rows[0], rows[1:]
            if len(set(header)) != len(header):
                diagnostics.append(f"slide {slide_i}'s table: duplicate/merged header cells")
                continue
            df = _coerce_numeric_columns(pd.DataFrame(body, columns=header))
            reason = _rejection_reason(df)
            if reason is None:
                tables.append(df)
            else:
                diagnostics.append(f"slide {slide_i}'s table: {reason}")
    if table_count == 0:
        diagnostics.append("this presentation has no tables at all — just slide text")
    return tables, diagnostics


def extract_tables(file_path: str, kind: str) -> tuple[list[pd.DataFrame], list[str]]:
    """Dispatches on the document's kind (see document_intelligence.py's
    SUPPORTED_EXTENSIONS). Returns (usable_tables, diagnostics) -
    usable_tables is every candidate that passed the cleanliness check
    (never a guess dressed up as a real table); diagnostics is a specific,
    human-readable reason for every candidate that DIDN'T, surfaced
    verbatim in the Ask screen's step trace (see planner.py) so "why
    didn't this get the structured treatment" is never a mystery. Always
    ([], ["PDF tables aren't ..."]) for "pdf" - see this module's
    docstring for why."""
    if kind == "xlsx":
        return _extract_xlsx_tables(file_path)
    if kind == "docx":
        return _extract_docx_tables(file_path)
    if kind == "pptx":
        return _extract_pptx_tables(file_path)
    if kind == "pdf":
        return [], ["PDF table structure detection isn't attempted (see the README's "
                    "\"Real PDF table structure detection\" note) — reading it as text instead."]
    return [], [f"unrecognized document kind {kind!r}"]


def _real_data_density(df: pd.DataFrame) -> int:
    """Non-null, non-zero numeric cells in non-ID columns - a proxy for
    "how much actual information is in here", not just how big the grid
    is. A real production example: a 15,738x18 unfilled KPI-tracking
    template (every real metric column either NaN or a placeholder 0)
    has more raw cells than a 4,140x67 sheet of genuine per-agent monthly
    figures, but virtually none of them mean anything - picking "biggest
    by cell count" alone would confidently hand the whole downstream
    analysis to the wrong, empty sheet. ID-like columns (a sequential
    row-number column, in particular) are excluded: a "No" column
    counting 1..15738 is numeric and non-zero for nearly every row, and
    would otherwise make an entirely empty template look richer than a
    real dataset just by being long."""
    numeric = df.select_dtypes(include="number")
    numeric = numeric[[c for c in numeric.columns if not _ID_LIKE_NAME.search(str(c))]]
    if numeric.empty:
        return 0
    return int(((numeric.notna()) & (numeric != 0)).sum().sum())


def pick_best_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    """The candidate with the most real data in it (see
    _real_data_density) - a document can have several tables (a workbook
    with a filled-in data sheet AND an unrelated blank template sheet, or
    a DOCX with one summary table and one contact-details table); this is
    the best default guess for "the actual dataset this question is
    about" without needing an extra LLM call just to choose between
    candidates. Falls back to raw cell count only as a tie-breaker
    between two candidates with equally little (e.g. both zero) real
    data, so a genuinely tied choice still resolves deterministically."""
    if not tables:
        return None
    return max(tables, key=lambda d: (_real_data_density(d), d.shape[0] * d.shape[1]))


def pick_group_columns(df: pd.DataFrame, limit: int = MAX_GROUP_COLUMNS) -> list[str]:
    candidates = []
    for col in df.columns:
        if df[col].dtype != object:
            continue
        if _ID_LIKE_NAME.search(str(col)):
            continue
        non_null = df[col].dropna()
        if len(non_null) == 0:
            continue
        # A column can stay `object` dtype without being a real category:
        # _coerce_numeric_columns only converts a column when >60% of its
        # values parse as numbers, so a sparse numeric column (a real
        # production example: a "Target" figure only set for some
        # agents, or a daily "31st" breakdown mostly blank) can sit right
        # at 40-60% numeric and stay text-typed - which would otherwise
        # get treated as a meaningful business dimension ("top Target:
        # 1250") instead of what it actually is: numeric data too sparse
        # to have been coerced. A real category column's values should
        # be overwhelmingly NOT parseable as numbers.
        if pd.to_numeric(non_null, errors="coerce").notna().mean() > 0.3:
            continue
        nunique = non_null.nunique()
        if 2 <= nunique <= min(MAX_GROUP_CARDINALITY, max(2, int(len(df) * 0.9))):
            candidates.append(col)
    # Columns whose name matches a known category keyword (store, region,
    # agent, product, ...) are far more likely to be a meaningful business
    # dimension than an arbitrary low-cardinality text column, so they're
    # tried first.
    candidates.sort(key=lambda c: 0 if any(k in str(c).lower() for k in _GROUP_KEYWORDS) else 1)
    return candidates[:limit]


_VALUE_KEYWORDS = ("value", "score", "total", "revenue", "sales", "amount", "achievement")


def pick_value_columns(df: pd.DataFrame, limit: int = MAX_VALUE_COLUMNS) -> list[str]:
    numeric = [c for c in df.select_dtypes(include="number").columns if not _ID_LIKE_NAME.search(str(c))]
    # A column literally named "value"/"score"/"total"/etc. (including
    # the reshaped "value" column _reshape_repeating_blocks produces for
    # a wide/blocked sheet's own composite metric) is almost always the
    # single most meaningful number in the table - tried first regardless
    # of where it happens to sit in raw column order.
    numeric.sort(key=lambda c: 0 if any(k in str(c).lower() for k in _VALUE_KEYWORDS) else 1)
    return numeric[:limit]


def pick_date_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if any(k in str(col).lower() for k in _DATE_KEYWORDS):
            return col
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col
    return None


def _extract_threshold(question: str) -> float | None:
    """A question mentioning "minimum at 60%" or "threshold 59%" is
    almost always describing ONE cutoff phrased two ways (>=60 is the
    same split as <=59), not two separate thresholds - the first
    percentage-like number mentioned is used as that cutoff."""
    match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", question)
    return float(match.group(1)) if match else None


@dataclass
class TabularProfile:
    row_count: int
    columns: list[str]
    primary_value_column: str | None
    primary_group_column: str | None
    date_column: str | None
    overall: dict
    breakdowns: dict[str, list[dict]]
    best_metric_per_group: dict[str, dict] | None
    trend: list[dict] | None
    threshold_band: dict | None


def build_profile(df: pd.DataFrame, question: str) -> TabularProfile:
    """The actual computation - every number below comes from pandas
    arithmetic on real parsed cells, never from the LLM. This is then
    handed to explain_document_only() (insight_agent.py) as
    "computed_profile", the same trust boundary explain()'s own
    "computed_metrics" already relies on for the database path."""
    group_cols = pick_group_columns(df)
    value_cols = pick_value_columns(df)
    date_col = pick_date_column(df)

    # A question naming a real column by (partial, case-insensitive) name
    # takes priority over the generic keyword/cardinality heuristics above
    # - "rank by agent" should use the agent column even if some other
    # column would otherwise sort first.
    q_lower = question.lower()
    named_group = next((c for c in group_cols if str(c).lower() in q_lower), None)
    named_value = next((c for c in value_cols if str(c).lower() in q_lower), None)
    primary_group = named_group or (group_cols[0] if group_cols else None)
    primary_value = named_value or (value_cols[0] if value_cols else None)

    overall = summarize(df, value_col=primary_value, group_col=primary_group, date_col=date_col).summary

    breakdowns: dict[str, list[dict]] = {}
    if primary_value:
        for gc in group_cols:
            grouped = df.groupby(gc)[primary_value].mean().sort_values(ascending=False)
            breakdowns[str(gc)] = [{"group": str(k), "value": round(float(v), 2)} for k, v in grouped.items()]

    # "Best-selling product per store/region" - for the primary group
    # column, which of the OTHER numeric columns has the highest total
    # within each group. Only computed when there's more than one
    # candidate value column (the primary one plus at least one more to
    # compare against) - otherwise there's nothing to pick a "best" from.
    best_metric_per_group = None
    other_value_cols = [c for c in value_cols if c != primary_value]
    if primary_group and other_value_cols:
        totals = df.groupby(primary_group)[other_value_cols].sum()
        best_metric_per_group = {
            str(g): {"metric": str(totals.loc[g].idxmax()), "total": round(float(totals.loc[g].max()), 2)}
            for g in totals.index
        }

    trend = None
    if date_col and primary_value:
        ts = df.copy()
        ts[date_col] = pd.to_datetime(ts[date_col], errors="coerce")
        ts = ts.dropna(subset=[date_col])
        if len(ts):
            periods = ts.groupby(ts[date_col].dt.to_period("M"))[primary_value].mean()
            if len(periods) >= 2:
                trend = [{"period": str(p), "average": round(float(v), 2)} for p, v in periods.items()]

    threshold_band = None
    threshold = _extract_threshold(question)
    if threshold is not None and primary_value:
        series = df[primary_value].dropna()
        # The column name matching score/percent/rate/achievement is a
        # strong signal, but not the only one worth trusting: a reshaped
        # wide-block sheet's own metric column (see
        # _reshape_repeating_blocks) is generically named "value" since
        # no semantic name survives the reshape - it's still exactly the
        # kind of thing a question naming a percentage threshold means to
        # band by. Falls back to checking the VALUES themselves look
        # plausibly percentage-scaled (median comfortably under 1000,
        # allowing for a >100% "percent of target" achievement metric)
        # rather than refusing just because of a generic column name.
        name_suggests_percent = bool(_PERCENT_LIKE_NAME.search(str(primary_value)))
        values_look_percent = len(series) > 0 and series.abs().median() < 1000
        if name_suggests_percent or values_look_percent:
            threshold_band = {
                "threshold_pct": threshold,
                "at_or_above_count": int((series >= threshold).sum()),
                "below_count": int((series < threshold).sum()),
            }

    return TabularProfile(
        row_count=len(df), columns=[str(c) for c in df.columns],
        primary_value_column=str(primary_value) if primary_value else None,
        primary_group_column=str(primary_group) if primary_group else None,
        date_column=str(date_col) if date_col else None,
        overall=overall, breakdowns=breakdowns,
        best_metric_per_group=best_metric_per_group, trend=trend, threshold_band=threshold_band,
    )


def profile_to_dict(profile: TabularProfile) -> dict:
    return asdict(profile)


def compute_data_quality_and_anomalies(df: pd.DataFrame, profile: TabularProfile):
    """Reuses the exact same data_quality.py/anomaly_detection.py the
    database path already relies on - a parsed table gets the same real
    completeness/duplicate/outlier checks and the same real anomaly
    detection a SQL result would, instead of document-only analysis's
    usual "Not applicable" placeholder for these steps."""
    quality = assess(df)
    anomalies = detect_anomalies(
        df, profile.primary_value_column, profile.primary_group_column, profile.date_column,
    )
    return quality, anomalies
