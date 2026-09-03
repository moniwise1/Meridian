"""
Best-effort column-role guessing, shared by the planner (on a query
result's columns) and the risk scan (on a table's own authorized column
list). Based on common naming conventions, kept deliberately simple and
transparent rather than another LLM call, per this app's running principle
of not using the LLM where deterministic logic suffices (see
anomaly_detection.py, analytics_engine.py).
"""


def guess_columns(columns: list[str]) -> tuple[str | None, str | None, str | None]:
    lc = {c.lower(): c for c in columns}
    value_col = next((lc[c] for c in lc if c in ("revenue", "sales", "amount", "total")), None)
    group_col = next((lc[c] for c in lc if c in ("region", "product", "branch", "state", "category")), None)
    date_col = next((lc[c] for c in lc if c in ("month", "date", "period", "created_at")), None)
    return value_col, group_col, date_col
