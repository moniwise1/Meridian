"""
Risk Scan Agent — proactive "find anything unusual across everything"
scanning, rather than anomaly detection only running against the current
question's result. Answers "give me the top five risks" without the user
having to already know which table or question to ask about.

Deliberately built with zero LLM calls, unlike the main /ask pipeline. This
isn't a shortcut — it's possible precisely because the query shape needed
here is always the same regardless of the table (group by two guessed
dimension columns, sum a guessed value column), so there's no natural-
language question to translate to SQL in the first place. Every other
security layer stays in place: policy-filtered schema in (tables come from
discover_schema, so a table's column list here is already restricted to
what the tenant's column_policy allows), the built SQL still goes through
validate_readonly_sql, executes through the same read-only connector as
any other query, and the result still goes through output_guard and a
row-scope check before it's used.

Row-scope handling differs from the main pipeline on purpose: /ask aborts
the single question on a violation (planner.PolicyViolation). A scan spans
many tables, so one table's violation shouldn't discard every other table's
legitimate results — that table's results are silently excluded from this
scan's output and the violation is still returned to the caller to audit-log,
exactly the way planner.py already logs (but does not silently swallow)
row_scope_violation events.
"""
from dataclasses import dataclass, field
import pandas as pd

from app.connectors.base import Connector, TableSchema
from app.agents.column_heuristics import guess_columns
from app.agents.anomaly_detection import Anomaly, detect
from app.security.query_validator import validate_readonly_sql
from app.security.output_guard import check_dataframe

MAX_TABLES_SCANNED = 10
_CONFIDENCE_RANK = {"high": 0, "moderate": 1, "low": 2}


@dataclass
class ScannedAnomaly:
    table: str
    anomaly: Anomaly


@dataclass
class ScanResult:
    scanned_anomalies: list[ScannedAnomaly] = field(default_factory=list)
    tables_scanned: list[str] = field(default_factory=list)
    tables_skipped: list[str] = field(default_factory=list)  # no guessable value/group/date columns
    row_scope_violations: list[str] = field(default_factory=list)  # table names excluded for this reason


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _build_scan_sql(table_name: str, group_col: str, date_col: str, value_col: str,
                     table_columns: set[str], row_scope: dict[str, list[str]]) -> str:
    where_clauses = []
    for col, vals in (row_scope or {}).items():
        # Only filterable if this table actually carries that dimension -
        # same "no column, no enforcement on this query" semantics
        # planner.py already uses for the main pipeline.
        if col not in table_columns or not vals:
            continue
        literals = ", ".join(_sql_literal(v) for v in vals)
        where_clauses.append(f"{col} IN ({literals})")
    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return (
        f"SELECT {group_col}, {date_col}, SUM({value_col}) AS {value_col} "
        f"FROM {table_name}{where_sql} "
        f"GROUP BY {group_col}, {date_col}"
    )


def scan_connection(connector: Connector, tables: list[TableSchema], row_scope: dict,
                     row_limit: int, timeout_seconds: int,
                     max_tables: int = MAX_TABLES_SCANNED) -> ScanResult:
    result = ScanResult()

    for table in tables[:max_tables]:
        table_columns = {c.name for c in table.columns}
        value_col, group_col, date_col = guess_columns([c.name for c in table.columns])
        if not (value_col and group_col and date_col):
            result.tables_skipped.append(table.name)
            continue

        sql = _build_scan_sql(table.name, group_col, date_col, value_col, table_columns, row_scope)
        validation = validate_readonly_sql(sql, row_limit)
        if not validation.is_valid:
            result.tables_skipped.append(table.name)
            continue

        try:
            query_result = connector.run_query(validation.normalized_sql, row_limit, timeout_seconds)
        except Exception:
            result.tables_skipped.append(table.name)
            continue

        df = query_result.dataframe
        output_check = check_dataframe(df, None, max_raw_rows=row_limit)
        if not output_check.allowed:
            result.tables_skipped.append(table.name)
            continue

        violated = False
        for scope_col, allowed_vals in (row_scope or {}).items():
            if scope_col in df.columns:
                offending = set(df[scope_col].dropna().unique()) - set(allowed_vals)
                if offending:
                    violated = True
                    break
        if violated:
            result.row_scope_violations.append(table.name)
            continue

        result.tables_scanned.append(table.name)
        for anomaly in detect(df, value_col, group_col, date_col):
            result.scanned_anomalies.append(ScannedAnomaly(table=table.name, anomaly=anomaly))

    result.scanned_anomalies.sort(key=lambda sa: _CONFIDENCE_RANK.get(sa.anomaly.confidence, 3))
    return result
