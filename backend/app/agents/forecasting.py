"""
Forecasting Agent — the "predictive" half of BUILD SPEC section 15's
descriptive/diagnostic/predictive/prescriptive categories (only the first
two existed before this). Deterministic, no LLM — same principle as
anomaly_detection.py and analytics_engine.py: numbers get computed here,
the LLM (if it comments on them at all) only ever interprets them.

Be honest about what this is: ordinary least squares on the already-
computed period totals, projected forward a few periods. It is NOT
forecasting in the ARIMA/Prophet/ML sense — no seasonality model, no
statistically-derived confidence interval, and it assumes the recent trend
continues, which is routinely wrong for real business data (a promotion
ending, a seasonal category, a one-off spike, a data pipeline gap). Every
place this surfaces says "if the recent trend continues", not "prediction"
or "forecast" unqualified, and the frontend renders it visually distinct
from anomalies/insight (dashed projection, not a fact).

"Prescriptive" analytics (what to DO about a projection) is deliberately
not attempted — that requires judgment this deterministic agent has no way
to exercise responsibly, and bolting an LLM opinion onto a number it didn't
compute risks the exact failure mode insight_agent.py's docstring warns
against (never introduce a figure — or here, a claim — the numbers don't
support).
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

MIN_PERIODS_REQUIRED = 3  # a "trend" through 2 points is just a line between 2 points
FLAT_THRESHOLD = 0.02  # relative slope below this reads as "flat" rather than up/down


@dataclass
class ForecastPoint:
    period: str
    projected_value: float


@dataclass
class Forecast:
    group: str
    method: str
    periods_used: int
    trend_direction: str  # "up" | "down" | "flat"
    points: list[ForecastPoint] = field(default_factory=list)
    caveat: str = ""


def forecast_by_group(df: pd.DataFrame, value_col: str | None, group_col: str | None,
                       date_col: str | None, periods_ahead: int = 3,
                       top_n_groups: int = 5) -> list[Forecast]:
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
    if len(periods) < MIN_PERIODS_REQUIRED:
        return []

    # Forecast only the current period's largest groups, bounded the same
    # way the risk scan bounds tables and the investigation cascade bounds
    # depth - "top N, not everything".
    latest = periods[-1]
    top_groups = pivot.loc[latest].dropna().sort_values(ascending=False).index[:top_n_groups]

    forecasts = []
    x_all = np.arange(len(periods))
    for grp in top_groups:
        series = pivot[grp]
        mask = series.notna()
        n = int(mask.sum())
        if n < MIN_PERIODS_REQUIRED:
            continue

        x = x_all[mask.values]
        y = series[mask.values].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, 1)

        points = [
            ForecastPoint(
                period=str(periods[-1] + i),
                projected_value=float(slope * (len(periods) - 1 + i) + intercept),
            )
            for i in range(1, periods_ahead + 1)
        ]

        mean_y = float(y.mean())
        if mean_y == 0:
            direction = "flat"
        else:
            relative_slope = slope / abs(mean_y)
            direction = "up" if relative_slope > FLAT_THRESHOLD else "down" if relative_slope < -FLAT_THRESHOLD else "flat"

        forecasts.append(Forecast(
            group=str(grp),
            method="linear trend (ordinary least squares) over the observed periods",
            periods_used=n,
            trend_direction=direction,
            points=points,
            caveat=(
                f"Based on {n} observed period(s) - a straight-line projection of the "
                f"recent trend, not a statistical forecast with a confidence interval. "
                f"Treat it as 'if this trend continues', not a guarantee - it has no way "
                f"to know about a promotion ending, seasonality, or anything else about "
                f"to change."
            ),
        ))
    return forecasts
