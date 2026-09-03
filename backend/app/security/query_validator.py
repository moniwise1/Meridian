"""
Read-only SQL validator.

This is layer 1 of defense-in-depth (see BUILD SPEC section 5). It is NOT
the primary security boundary by itself — the Postgres connector also opens
every session in `SET TRANSACTION READ ONLY` mode (a real database-level
control) and the recommended DB role has no write grants at all. This
validator exists to fail fast, with a clear reason, before a query ever
reaches the database.
"""
import re
import sqlparse
from dataclasses import dataclass

FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "GRANT", "REVOKE", "MERGE", "EXEC", "EXECUTE", "CALL", "COPY",
    "VACUUM", "REINDEX", "REPLACE", "ATTACH", "DETACH", "PRAGMA",
}

# Statement types sqlparse will accept as the *only* thing in the query.
ALLOWED_STATEMENT_STARTS = ("SELECT", "WITH")


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str = ""
    normalized_sql: str = ""


def validate_readonly_sql(sql: str, row_limit: int) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(False, "Empty query.")

    statements = [s for s in sqlparse.parse(sql) if s.tokens]
    if len(statements) != 1:
        return ValidationResult(False, "Only a single SELECT statement is permitted per query.")

    stmt = statements[0]
    stmt_str = str(stmt).strip()

    # Reject stacked statements (e.g. "SELECT 1; DROP TABLE x;")
    if stmt_str.rstrip(";").count(";") > 0:
        return ValidationResult(False, "Stacked / multiple statements are not permitted.")

    first_token = stmt.token_first(skip_cm=True)
    if first_token is None or first_token.value.upper() not in ALLOWED_STATEMENT_STARTS:
        return ValidationResult(False, "Only SELECT (or WITH ... SELECT) statements are permitted.")

    upper_sql = stmt_str.upper()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper_sql):
            return ValidationResult(False, f"Forbidden keyword detected: {kw}.")

    # Block comment-based smuggling (e.g. "SELECT 1 -- ; DROP TABLE x")
    if "--" in stmt_str or "/*" in stmt_str:
        return ValidationResult(False, "SQL comments are not permitted in generated queries.")

    normalized = stmt_str.rstrip(";")
    if not re.search(r"\bLIMIT\s+\d+\b", upper_sql):
        normalized = f"{normalized} LIMIT {row_limit}"

    return ValidationResult(True, normalized_sql=normalized)
