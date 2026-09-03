"""
Connector interface (BUILD SPEC section 4). Every data source integration
implements this contract so the rest of the system (schema discovery, query
generation, execution) never needs to know which underlying system it's
talking to.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd


@dataclass
class ColumnInfo:
    name: str
    data_type: str


@dataclass
class TableSchema:
    name: str
    columns: list[ColumnInfo]


@dataclass
class QueryResult:
    dataframe: pd.DataFrame
    duration_ms: int
    truncated: bool


class Connector(ABC):
    """All connectors are read-only by contract. There is no write/execute
    path on this interface at all — it does not exist to be disabled, it
    was never built."""

    @abstractmethod
    def test_connection(self) -> bool:
        ...

    @abstractmethod
    def verify_read_only(self) -> bool:
        """Positively confirm the credential cannot mutate data, e.g. by
        attempting a no-op write inside a transaction that is always rolled
        back and asserting it fails. Called once at connection-setup time
        and surfaced to the tenant admin."""
        ...

    @abstractmethod
    def get_schema(self, table_allowlist: list[str] | None) -> list[TableSchema]:
        ...

    @abstractmethod
    def run_query(self, sql: str, row_limit: int, timeout_seconds: int) -> QueryResult:
        ...
