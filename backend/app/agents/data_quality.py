"""
Data Quality Agent (BUILD SPEC section 14).

Deterministic checks only — no LLM involved. Results are attached to every
analysis so findings are never presented without their quality context, and
cleaning is never silent.
"""
from dataclasses import dataclass, field
import pandas as pd
import numpy as np


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

    notes = []
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
