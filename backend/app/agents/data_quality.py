"""
Data Quality Agent (BUILD SPEC section 14).

Deterministic checks only — no LLM involved. Results are attached to every
analysis so findings are never presented without their quality context, and
cleaning is never silent.
"""
from dataclasses import dataclass, field
import re
import pandas as pd
import numpy as np

# Same column-name heuristic tabular_analysis.py uses to decide whether a
# threshold_band question applies to a column - duplicated rather than
# imported to avoid a circular import (tabular_analysis.py imports assess()
# from this module).
_PERCENT_LIKE_NAME = re.compile(r"score|percent|%|rate|achievement", re.IGNORECASE)

# A percent/rate/score-named column holding a value this far from zero is
# almost certainly a data or parsing error, not a real observation - this is
# the check that would have caught the real "9420.0%" figure in a shipping
# company's on-time-delivery report.
_IMPLAUSIBLE_MAGNITUDE = 1000

# Same shallow spirit as tabular_analysis.py's documented decision not to
# parse PDF table structure: a plain text scan can't know whether a number
# before a "%" is a typo, OCR noise, or a genuinely large percentage - it can
# only flag it for the reader to check, not "correct" it. Matched values are
# filtered against _IMPLAUSIBLE_MAGNITUDE below rather than by digit count,
# so an ordinary (if unusual) figure like "150%" is left alone.
_PERCENT_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)\s?%")


@dataclass
class DataQualityReport:
    row_count: int
    completeness_pct: float
    duplicate_pct: float
    missing_by_column: dict = field(default_factory=dict)
    outlier_notes: list = field(default_factory=list)
    excluded_row_count: int = 0
    notes: list = field(default_factory=list)


def assess(df: pd.DataFrame) -> DataQualityReport:
    row_count = len(df)
    if row_count == 0:
        return DataQualityReport(0, 0.0, 0.0, notes=["Query returned zero rows."])

    missing_by_column = {
        col: round(df[col].isna().mean() * 100, 2)
        for col in df.columns
        if df[col].isna().any()
    }
    total_cells = df.shape[0] * df.shape[1]
    missing_cells = int(df.isna().sum().sum())
    completeness_pct = round(100 * (1 - missing_cells / total_cells), 2) if total_cells else 100.0

    duplicate_pct = round(df.duplicated().mean() * 100, 2)

    outlier_notes = []
    plausibility_notes = []
    for col in df.select_dtypes(include=[np.number]).columns:
        series = df[col].dropna()
        if len(series) < 8:
            continue
        mean, std = series.mean(), series.std()
        if std == 0 or np.isnan(std):
            continue
        z = (series - mean) / std
        n_outliers = int((z.abs() > 3).sum())
        if n_outliers > 0:
            outlier_notes.append(f"{n_outliers} statistical outlier(s) detected in '{col}' (|z| > 3).")

        if _PERCENT_LIKE_NAME.search(str(col)):
            implausible = series[series.abs() > _IMPLAUSIBLE_MAGNITUDE]
            if len(implausible) > 0:
                plausibility_notes.append(
                    f"'{col}' looks like a percentage/rate/score column but has {len(implausible)} "
                    f"value(s) far outside a plausible range (e.g. {implausible.iloc[0]:g}) — this "
                    "likely reflects a data or parsing error rather than a real observation. Treat "
                    "with caution and verify against the source."
                )

    # Plausibility flags lead the list - they're the ones most likely to
    # change whether a reader trusts the numbers at all, ahead of routine
    # completeness/duplicate notes.
    notes = list(plausibility_notes)
    if completeness_pct < 100:
        notes.append(f"{100 - completeness_pct:.1f}% of cells across the result set are missing values.")
    if duplicate_pct > 0:
        notes.append(f"{duplicate_pct:.1f}% of rows are exact duplicates.")

    return DataQualityReport(
        row_count=row_count,
        completeness_pct=completeness_pct,
        duplicate_pct=duplicate_pct,
        missing_by_column=missing_by_column,
        outlier_notes=outlier_notes,
        notes=notes,
    )


def scan_text_for_implausible_percentages(text: str) -> list:
    """Regex-only plausibility check for raw document text - used when no
    real table was parsed (e.g. a PDF with no extractable table), so there
    are no columns to run assess() against. Deliberately shallow: it can
    only flag a suspicious-looking figure for the reader to verify, not
    determine whether it is genuinely wrong.
    """
    matches = sorted(
        {m.group(1) for m in _PERCENT_IN_TEXT.finditer(text or "") if float(m.group(1)) > _IMPLAUSIBLE_MAGNITUDE},
        key=float,
        reverse=True,
    )[:5]
    if not matches:
        return []
    plural = len(matches) > 1
    return [
        f"Found {'values' if plural else 'a value'} in the document text that read"
        f" {'as percentages' if plural else 'as a percentage'} far outside a plausible range"
        f" (e.g. {matches[0]}%) — this may be a typo, an OCR/extraction artifact, or a genuine"
        " data error. Treat with caution and verify against the source document."
    ]
