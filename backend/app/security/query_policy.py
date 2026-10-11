"""Authorize SQL against the discovered schema, before any database execution.

SQLGlot resolves aliases/CTEs and column references. Restricted source tables
are replaced with server-built projections and bound row predicates before
aggregation. Prompt instructions and output column names are not boundaries.
"""
from dataclasses import dataclass
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import traverse_scope
from app.security.output_guard import DEFAULT_SENSITIVE_COLUMN_PATTERNS


class QueryPolicyError(ValueError):
    pass


@dataclass
class AuthorizedQuery:
    sql: str
    params: dict


DIALECTS = {"postgres": "postgres", "mysql": "mysql", "mssql": "tsql", "snowflake": "snowflake"}
# Unknown database functions can have side effects even in SELECT statements.
SAFE_ANONYMOUS = {"DATE_FORMAT", "STRFTIME", "ISNULL", "DATEDIFF", "DATEADD"}


def authorize_query(sql, tables, row_scope, row_limit, kind="postgres"):
    dialect = DIALECTS.get(kind, "postgres")
    try:
        statements = sqlglot.parse(sql, read=dialect)
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise QueryPolicyError("Only a supported read-only query is permitted.")
        tree = normalize_identifiers(statements[0], dialect=dialect)
        if any(tree.find_all(exp.Into, exp.Lock, exp.Command, exp.NextValueFor)):
            raise QueryPolicyError("Query contains an unsupported operation.")
        for fn in tree.find_all(exp.Anonymous):
            if fn.name.upper() not in SAFE_ANONYMOUS:
                raise QueryPolicyError("Query uses an unapproved database function.")
        schema = {(t.name.upper() if dialect == "snowflake" else t.name):
            {(c.name.upper() if dialect == "snowflake" else c.name): "UNKNOWN" for c in t.columns
             if not any(pattern in c.name.lower() for pattern in DEFAULT_SENSITIVE_COLUMN_PATTERNS)} for t in tables}
        base_tables = []
        for scope in traverse_scope(tree):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    if source.db or source.catalog or source.name not in schema:
                        raise QueryPolicyError("Query references an unauthorized table.")
                    base_tables.append(source)
        if not base_tables:
            raise QueryPolicyError("Query must use an authorized source table.")
        # Fail on unknown/ambiguous columns, including expressions and aliases.
        tree = qualify(tree, dialect=dialect, schema=schema, validate_qualify_columns=True,
                       quote_identifiers=True, identify=True)
        params = {}
        if row_scope:
            # Re-resolve after qualify copied/normalized the tree.
            base_tables = []
            for scope in traverse_scope(tree):
                for _, source in scope.selected_sources.values():
                    if isinstance(source, exp.Table):
                        base_tables.append(source)
            for index, table in enumerate(base_tables):
                columns = schema[table.name]
                predicates = []
                for column, values in row_scope.items():
                    column = column.upper() if dialect == "snowflake" else column
                    if column not in columns:
                        raise QueryPolicyError("This source cannot enforce your row permissions.")
                    if not values:
                        predicates.append(exp.false())
                        continue
                    placeholders = []
                    for n, value in enumerate(values):
                        key = f"meridian_scope_{index}_{len(predicates)}_{n}"
                        params[key] = value
                        placeholders.append(exp.Placeholder(this=key))
                    predicates.append(exp.In(this=exp.column(column, quoted=True), expressions=placeholders))
                projection = exp.select(*[exp.column(c, quoted=True) for c in columns]).from_(
                    exp.Table(this=table.this.copy()))
                projection = projection.where(exp.and_(*predicates))
                replacement = projection.subquery(copy=False)
                replacement.set("alias", exp.TableAlias(this=exp.to_identifier(table.alias_or_name, quoted=True)))
                table.replace(replacement)
        # Clamp the root query's limit while preserving its ordering and CTEs.
        # Dialect generation emits TOP for SQL Server and LIMIT elsewhere.
        cap = int(row_limit)
        existing = tree.args.get("limit")
        if existing and isinstance(existing.expression, exp.Literal) and existing.expression.is_int:
            cap = max(0, min(cap, int(existing.expression.this)))
        tree = tree.limit(cap)
        return AuthorizedQuery(tree.sql(dialect=dialect), params)
    except QueryPolicyError:
        raise
    except Exception as exc:
        raise QueryPolicyError("Query could not be verified against your authorized schema.") from exc


def execute_authorized(connector, sql, tables, row_scope, row_limit, timeout_seconds, kind="postgres"):
    query = authorize_query(sql, tables, row_scope, row_limit, kind)
    if query.params:
        result = connector.run_query(query.sql, row_limit, timeout_seconds, params=query.params)
    else:
        result = connector.run_query(query.sql, row_limit, timeout_seconds)
    return query, result
