"""
Schema Discovery Agent (BUILD SPEC section 10).

Turns a connector's raw schema into a compact, POLICY-FILTERED description
suitable for handing to the LLM. Columns not in the tenant's column_policy
allowlist for a table are never included here, so the model literally
cannot generate SQL that references them.
"""
from app.connectors.base import Connector, TableSchema


def discover_schema(connector: Connector, table_allowlist: list[str] | None,
                     column_policy: dict[str, list[str]]) -> list[TableSchema]:
    raw_tables = connector.get_schema(table_allowlist)
    filtered = []
    for table in raw_tables:
        allowed_cols = column_policy.get(table.name)
        if allowed_cols is None:
            # No explicit policy configured for this table -> allow all
            # (tenant admins should configure this in production; MVP
            # default is permissive per-table but the sensitive-pattern
            # blocklist in output_guard still applies as a backstop).
            filtered.append(table)
        else:
            cols = [c for c in table.columns if c.name in allowed_cols]
            if cols:
                filtered.append(TableSchema(name=table.name, columns=cols))
    return filtered


def schema_to_prompt_text(tables: list[TableSchema]) -> str:
    lines = []
    for t in tables:
        col_desc = ", ".join(f"{c.name} ({c.data_type})" for c in t.columns)
        lines.append(f"- {t.name}: {col_desc}")
    return "\n".join(lines)
