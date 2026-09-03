"""
Output security / DLP check (BUILD SPEC section 21).

Runs on every result set before it is shown to the user or handed to the
LLM for interpretation. Enforces column-level policy and prefers aggregated
results over raw record dumps.
"""
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class OutputCheckResult:
    allowed: bool
    reason: str = ""
    blocked_columns: list = field(default_factory=list)


DEFAULT_SENSITIVE_COLUMN_PATTERNS = (
    "password", "national_id", "ssn", "bank_account", "card_number",
    "full_card_number", "credit_card", "secret", "api_key", "token",
)


def check_dataframe(df: pd.DataFrame, allowed_columns: set[str] | None,
                     max_raw_rows: int) -> OutputCheckResult:
    """
    allowed_columns: the tenant's explicit column allowlist for this
    connection (None means "not restricted beyond default sensitive-pattern
    blocking" — tenants should always configure this in production).
    """
    blocked = []
    for col in df.columns:
        lc = col.lower()
        if any(p in lc for p in DEFAULT_SENSITIVE_COLUMN_PATTERNS):
            blocked.append(col)
        if allowed_columns is not None and col not in allowed_columns:
            blocked.append(col)

    if blocked:
        return OutputCheckResult(False, "Query touched columns outside the authorized allowlist.", blocked)

    if len(df) > max_raw_rows:
        return OutputCheckResult(
            False,
            f"Result set ({len(df)} rows) exceeds the raw-record export threshold "
            f"({max_raw_rows}); return an aggregated summary instead.",
        )

    return OutputCheckResult(True)
