"""
Analytics Engine (BUILD SPEC section 11).

Deterministic pandas computation. The LLM never does arithmetic — it only
ever receives numbers that were already computed here, and interprets them.
This is the single biggest lever against hallucinated statistics.
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class ComputedMetrics:
    summary: dict
    by_group: list[dict] | None = None


def summarize(df: pd.DataFrame, value_col: str | None = None,
              group_col: str | None = None, date_col: str | None = None) -> ComputedMetrics:
    summary: dict = {"row_count": len(df)}
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    if value_col and value_col in df.columns:
        summary["total"] = float(df[value_col].sum())
        summary["mean"] = float(df[value_col].mean()) if len(df) else 0.0
        summary["min"] = float(df[value_col].min()) if len(df) else 0.0
        summary["max"] = float(df[value_col].max()) if len(df) else 0.0

    by_group = None
    if group_col and value_col and group_col in df.columns and value_col in df.columns:
        grouped = df.groupby(group_col)[value_col].sum().sort_values(ascending=False)
        by_group = [{"group": str(k), "total": float(v)} for k, v in grouped.items()]

        total = grouped.sum()
        if total:
            summary["top_contributor"] = by_group[0]["group"]
            summary["top_contributor_share_pct"] = round(100 * by_group[0]["total"] / total, 2)

    if date_col and value_col and date_col in df.columns and value_col in df.columns:
        ts = df.copy()
        ts[date_col] = pd.to_datetime(ts[date_col], errors="coerce")
        ts = ts.dropna(subset=[date_col]).sort_values(date_col)
        periods = ts.groupby(ts[date_col].dt.to_period("M"))[value_col].sum()
        if len(periods) >= 2:
            current, previous = periods.iloc[-1], periods.iloc[-2]
            growth = ((current - previous) / previous * 100) if previous else None
            summary["latest_period"] = str(periods.index[-1])
            summary["previous_period"] = str(periods.index[-2])
            summary["period_over_period_growth_pct"] = round(growth, 2) if growth is not None else None
        elif len(numeric_cols) == 0:
            pass

    return ComputedMetrics(summary=summary, by_group=by_group)
