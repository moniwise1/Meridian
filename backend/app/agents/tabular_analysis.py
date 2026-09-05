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

_ID_LIKE_NAME = re.compile(r"\b(id|uuid|no|code|key|number|#)\b", re.IGNORECASE)
_GROUP_KEYWORDS = ("store", "region", "state", "agent", "branch", "product", "category",
                    "department", "shop", "outlet", "supervisor", "manager", "zone", "area")
_DATE_KEYWORDS = ("date", "month", "period", "week", "year", "day")
_PERCENT_LIKE_NAME = re.compile(r"score|percent|%|rate|achievement", re.IGNORECASE)


def _is_usable_table(df: pd.DataFrame) -> bool:
    if df is None or df.shape[0] < MIN_TABLE_ROWS or df.shape[1] < 2:
        return False
    if df.shape[1] > MAX_TABLE_COLUMNS:
        return False
    unnamed = sum(1 for c in df.columns if str(c).startswith("Unnamed:") or str(c).strip() == "")
    if unnamed / df.shape[1] > MAX_UNNAMED_COLUMN_RATIO:
        return False
    numeric_cols = df.select_dtypes(include="number").columns
    coerced_numeric = sum(
        1 for c in df.columns if c not in numeric_cols and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.6
    )
    return len(numeric_cols) + coerced_numeric > 0


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


def _extract_xlsx_tables(file_path: str) -> list[pd.DataFrame]:
    try:
        sheets = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")
    except Exception:
        return []
    tables = []
    for name, df in list(sheets.items())[:MAX_SHEETS_TRIED]:
        df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
        if _is_usable_table(df):
            tables.append(df)
    return tables


def _table_from_docx_table(table) -> pd.DataFrame | None:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if len(rows) < MIN_TABLE_ROWS + 1:
        return None
    header, body = rows[0], rows[1:]
    if len(set(header)) != len(header):  # duplicate header cells (a merged-cell table) - not a clean flat table
        return None
    return pd.DataFrame(body, columns=header)


def _extract_docx_tables(file_path: str) -> list[pd.DataFrame]:
    try:
        document = docx.Document(file_path)
    except Exception:
        return []
    tables = []
    for table in document.tables:
        df = _table_from_docx_table(table)
        if df is not None:
            df = _coerce_numeric_columns(df)
            if _is_usable_table(df):
                tables.append(df)
    return tables


def _extract_pptx_tables(file_path: str) -> list[pd.DataFrame]:
    try:
        presentation = pptx.Presentation(file_path)
    except Exception:
        return []
    tables = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
            if len(rows) < MIN_TABLE_ROWS + 1:
                continue
            header, body = rows[0], rows[1:]
            if len(set(header)) != len(header):
                continue
            df = _coerce_numeric_columns(pd.DataFrame(body, columns=header))
            if _is_usable_table(df):
                tables.append(df)
    return tables


def extract_tables(file_path: str, kind: str) -> list[pd.DataFrame]:
    """Dispatches on the document's kind (see document_intelligence.py's
    SUPPORTED_EXTENSIONS). Returns every candidate table that passed
    _is_usable_table's cleanliness check - never a guess dressed up as a
    real table. Always [] for "pdf" - see this module's docstring."""
    if kind == "xlsx":
        return _extract_xlsx_tables(file_path)
    if kind == "docx":
        return _extract_docx_tables(file_path)
    if kind == "pptx":
        return _extract_pptx_tables(file_path)
    return []


def pick_best_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    """The largest usable table by cell count - a document can have
    several small unrelated tables (a DOCX with one summary table and one
    contact-details table); the biggest one is the best default guess for
    "the actual dataset this question is about" without needing an extra
    LLM call just to choose between candidates."""
    if not tables:
        return None
    return max(tables, key=lambda d: d.shape[0] * d.shape[1])


def pick_group_columns(df: pd.DataFrame, limit: int = MAX_GROUP_COLUMNS) -> list[str]:
    candidates = []
    for col in df.columns:
        if df[col].dtype != object:
            continue
        if _ID_LIKE_NAME.search(str(col)):
            continue
        nunique = df[col].nunique(dropna=True)
        if 2 <= nunique <= min(MAX_GROUP_CARDINALITY, max(2, int(len(df) * 0.9))):
            candidates.append(col)
    # Columns whose name matches a known category keyword (store, region,
    # agent, product, ...) are far more likely to be a meaningful business
    # dimension than an arbitrary low-cardinality text column, so they're
    # tried first.
    candidates.sort(key=lambda c: 0 if any(k in str(c).lower() for k in _GROUP_KEYWORDS) else 1)
    return candidates[:limit]


def pick_value_columns(df: pd.DataFrame, limit: int = MAX_VALUE_COLUMNS) -> list[str]:
    numeric = df.select_dtypes(include="number").columns
    return [c for c in numeric if not _ID_LIKE_NAME.search(str(c))][:limit]


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
    if threshold is not None and primary_value and _PERCENT_LIKE_NAME.search(str(primary_value)):
        series = df[primary_value].dropna()
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
