"""
Investigation Agent (BUILD SPEC sections 10, 12, 16). When an anomaly is
found, automatically cascades through additional authorized, validated
queries to break the affected segment down by further available dimensions
- the "decline -> by state -> by product -> by branch" drill-down the
spec's example plan describes, generalized to whatever dimension columns
the authorized schema actually has. Each level filters to the *top*
contributor found at the level above, so the cascade follows where the
change is actually concentrated rather than branching out.

Reuses query_generator + query_validator + the connector exactly as the
main flow does: an investigation query is not a special, less-checked path.

Bounded by MAX_CASCADE_DEPTH so one anomaly can never trigger an unbounded
chain of extra queries - it stops early on its own once it runs out of
schema dimensions it hasn't already used.
"""
from dataclasses import dataclass
import pandas as pd

from app.agents.anomaly_detection import Anomaly
from app.agents.query_generator import generate_sql
from app.security.query_validator import validate_readonly_sql
from app.connectors.base import Connector, TableSchema


@dataclass
class InvestigationResult:
    dimension: str
    breakdown: list[dict]
    sql: str
    top_group: str | None = None


CANDIDATE_DIMENSIONS = ("product", "branch", "category", "channel", "segment", "customer_type", "state", "region")
MAX_CASCADE_DEPTH = 3


def investigate(connector: Connector, tables: list[TableSchema], schema_text: str,
                 value_col: str, filters: dict[str, str], already_used: set[str],
                 change_description: str, row_limit: int, timeout_seconds: int) -> InvestigationResult | None:
    """One drill-down level: breaks value_col down by the next unused
    candidate dimension, filtered to the (column -> value) pairs accumulated
    from every level above it."""
    available_cols = {c.name.lower() for t in tables for c in t.columns}
    next_dim = next(
        (d for d in CANDIDATE_DIMENSIONS if d in available_cols and d not in already_used),
        None,
    )
    if next_dim is None:
        return None

    filter_clause = " and ".join(f"{col} = '{val}'" for col, val in filters.items())
    question = (
        f"Break down {value_col} by {next_dim}"
        + (f" where {filter_clause}" if filter_clause else "")
        + f", for the most recent two periods, so we can see which {next_dim} contributed most "
        f"to the change described as: {change_description}"
    )
    generated = generate_sql(question, schema_text)
    if not generated.sql:
        return None

    validation = validate_readonly_sql(generated.sql, row_limit)
    if not validation.is_valid:
        return None

    result = connector.run_query(validation.normalized_sql, row_limit, timeout_seconds)
    df = result.dataframe
    if next_dim not in df.columns or value_col not in df.columns:
        return None

    grouped = df.groupby(next_dim)[value_col].sum().sort_values(ascending=False)
    if grouped.empty:
        return None
    breakdown = [{"group": str(k), "total": float(v)} for k, v in grouped.items()]
    top_group = str(grouped.index[0])
    return InvestigationResult(dimension=next_dim, breakdown=breakdown, sql=validation.normalized_sql, top_group=top_group)


def investigate_cascade(connector: Connector, tables: list[TableSchema], schema_text: str,
                         anomaly: Anomaly, group_col: str, value_col: str,
                         row_limit: int, timeout_seconds: int,
                         max_depth: int = MAX_CASCADE_DEPTH) -> list[InvestigationResult]:
    """Drills down repeatedly: the top contributor found at each level
    becomes an additional filter for the next, so a "revenue declined in
    South-East" anomaly can cascade South-East -> its top product ->
    that product's top branch, each level narrowing in on where the change
    is actually concentrated. Stops as soon as a level finds nothing
    (no unused dimension left, or the query returns no groups), so it never
    runs deeper than the schema actually supports."""
    results: list[InvestigationResult] = []
    already_used = {group_col.lower()}
    filters = {group_col: anomaly.segment}
    change_description = anomaly.what

    for _ in range(max_depth):
        result = investigate(
            connector, tables, schema_text, value_col, filters, already_used,
            change_description, row_limit, timeout_seconds,
        )
        if not result or not result.top_group:
            break
        results.append(result)
        already_used.add(result.dimension.lower())
        filters[result.dimension] = result.top_group

    return results
