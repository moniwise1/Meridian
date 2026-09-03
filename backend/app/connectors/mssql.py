"""
Microsoft SQL Server connector.

Worth being explicit about, unlike the Postgres/MySQL connectors: T-SQL has
no equivalent of `BEGIN TRANSACTION READ ONLY` that makes a session
structurally incapable of writing. There is no engine-level read-only
transaction mode to fall back on here. Enforcement therefore rests entirely
on the connecting role's own GRANTs being SELECT-only —
`verify_read_only()` proves that by attempting a real, rolled-back write
and checking SQL Server rejects it, the same probe pattern as the other
connectors. But a role that's *mis-configured* with write access would
slip a write through where Postgres/MySQL would still block it at the
session level regardless of grants. The README's recommended GRANT
statements matter more for this connector than for the others — don't
treat `verified_read_only=True` here as the same strength of guarantee.

Similarly, `SET LOCK_TIMEOUT` bounds how long a query waits on another
transaction's locks; it does not cap a long-running scan the way Postgres's
`statement_timeout` does — SQL Server has no per-statement CPU/time limit
reachable from a plain connection, so `timeout_seconds` is best-effort here
against lock contention, not a hard ceiling on runaway queries.
"""
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, text, inspect
import pandas as pd

from app.connectors.base import Connector, TableSchema, ColumnInfo, QueryResult
from app.security.secrets import RedactedSecret


class MSSQLConnector(Connector):
    def __init__(self, host: str, port: int, database: str, username: str,
                 password: RedactedSecret, timeout_seconds: int = 15):
        url = (
            f"mssql+pymssql://{username}:{password.reveal()}"
            f"@{host}:{port}/{database}"
        )
        self._engine = create_engine(url, pool_pre_ping=True, pool_size=3)

    @contextmanager
    def _readonly_conn(self, timeout_seconds: int):
        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.execute(text(f"SET LOCK_TIMEOUT {int(timeout_seconds * 1000)}"))
            conn.execute(text("BEGIN TRANSACTION"))
            try:
                yield conn
                conn.execute(text("COMMIT"))
            except Exception:
                conn.execute(text("ROLLBACK"))
                raise
        finally:
            conn.close()

    def test_connection(self) -> bool:
        try:
            with self._readonly_conn(5) as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def verify_read_only(self) -> bool:
        """SQL Server DDL is transactional, so a rolled-back CREATE TABLE
        genuinely leaves no trace when it succeeds — same as the temp-table
        probe the Postgres/MySQL connectors use. See module docstring for
        why "rejected" here proves a role-level grant, not a session-level
        guarantee."""
        try:
            with self._engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("BEGIN TRANSACTION"))
                try:
                    conn.execute(text("CREATE TABLE #_ro_probe (x INT)"))
                    conn.execute(text("ROLLBACK"))
                    return False  # mutation was NOT rejected -> not safely read-only
                except Exception:
                    conn.execute(text("ROLLBACK"))
                    return True  # mutation was rejected, as required
        except Exception:
            return False

    def get_schema(self, table_allowlist: list[str] | None) -> list[TableSchema]:
        inspector = inspect(self._engine)
        result = []
        for table_name in inspector.get_table_names():
            if table_allowlist and table_name not in table_allowlist:
                continue
            cols = inspector.get_columns(table_name)
            result.append(TableSchema(
                name=table_name,
                columns=[ColumnInfo(c["name"], str(c["type"])) for c in cols],
            ))
        return result

    def run_query(self, sql: str, row_limit: int, timeout_seconds: int) -> QueryResult:
        start = time.time()
        with self._readonly_conn(timeout_seconds) as conn:
            df = pd.read_sql(text(sql), conn)
        truncated = len(df) >= row_limit
        duration_ms = int((time.time() - start) * 1000)
        return QueryResult(dataframe=df, duration_ms=duration_ms, truncated=truncated)
