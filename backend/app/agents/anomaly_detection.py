"""
Anomaly Detection Agent (BUILD SPEC section 16). Deterministic - no LLM.

Flags:
- a group whose period-over-period change is a statistical outlier relative
  to the other groups' changes (z-score on growth rate, not on the raw
  value, so a big group and a small group are compared fairly)
- missing periods for a group that has data in other periods (the
  "operational outlier" / "missing data" case from the spec)

Every anomaly carries what/magnitude/timeframe/segment/evidence/confidence,
per section 16, and never asserts causation - "the data suggests" phrasing
is enforced at construction time, not left to the LLM to remember.
"""
from dataclasses import dataclass, field
import pandas as pd
import numpy as np


@dataclass
class Anomaly:
    what: str
    magnitude: str
    timeframe: str
    segment: str
    evidence: str
    confidence: str  # "high" | "moderate" | "low"
    possible_explanations: list[str] = field(default_factory=list)


def detect(df: pd.DataFrame, value_col: str | None, group_col: str | None,
           date_col: str | None) -> list[Anomaly]:
    if not (value_col and group_col and date_col):
        return []
    if value_col not in df.columns or group_col not in df.columns or date_col not in df.columns:
        return []

    work = df.copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    if work.empty:
        return []

    work["_period"] = work[date_col].dt.to_period("M")
    pivot = work.groupby(["_period", group_col])[value_col].sum().unstack(fill_value=np.nan)
    periods = sorted(pivot.index)
    if len(periods) < 2:
        return []

    anomalies: list[Anomaly] = []
    current, previous = periods[-1], periods[-2]

    growth_rates = {}
    for grp in pivot.columns:
        prev_val, cur_val = pivot.loc[previous, grp], pivot.loc[current, grp]
        if pd.isna(prev_val) or pd.isna(cur_val):
            continue
        if prev_val == 0:
            continue
        growth_rates[grp] = (cur_val - prev_val) / prev_val

    if len(growth_rates) >= 3:
        rates = pd.Series(growth_rates)
        mean, std = rates.mean(), rates.std()
        if std and not np.isnan(std):
            z = (rates - mean) / std
            for grp, z_score in z.items():
                if abs(z_score) > 1.3:
                    direction = "declined" if growth_rates[grp] < 0 else "increased"
                    anomalies.append(Anomaly(
                        what=f"{grp} {direction} sharply relative to the rest of the group.",
                        magnitude=f"{growth_rates[grp] * 100:+.1f}% vs. the previous period "
                                  f"(z-score {z_score:+.2f} against peer groups).",
                        timeframe=f"{previous} -> {current}",
                        segment=str(grp),
                        evidence=f"{group_col}='{grp}': {pivot.loc[previous, grp]:.0f} -> {pivot.loc[current, grp]:.0f}.",
                        confidence="moderate" if abs(z_score) < 2.5 else "high",
                        possible_explanations=[
                            "The data suggests a genuine shift in this segment rather than "
                            "normal period-to-period noise, but the cause is not yet established.",
                        ],
                    ))

    # Missing-period check: a group with data in earlier periods but not the latest.
    for grp in pivot.columns:
        history = pivot[grp].dropna()
        if len(history) >= 1 and pd.isna(pivot.loc[current, grp]) and not pd.isna(pivot.loc[previous, grp]):
            anomalies.append(Anomaly(
                what=f"No data recorded for {grp} in the most recent period.",
                magnitude="100% drop to zero recorded activity.",
                timeframe=str(current),
                segment=str(grp),
                evidence=f"{group_col}='{grp}' had data in {previous} but none in {current}.",
                confidence="moderate",
                possible_explanations=[
                    "The data suggests either a genuine operational stop or a reporting/pipeline gap "
                    "for this segment - worth confirming before treating it as a real decline.",
                ],
            ))

    return anomalies
