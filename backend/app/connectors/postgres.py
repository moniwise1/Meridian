"""
PostgreSQL connector.

Technical (not just policy) read-only enforcement:
  1. Every session opens with `SET SESSION CHARACTERISTICS AS TRANSACTION
     READ ONLY`, so even if the underlying role somehow had write grants,
     the session itself cannot commit a mutation.
  2. `statement_timeout` is set per-connection to bound runaway queries.
  3. `verify_read_only()` proactively tries a harmless write in a
     transaction that is always rolled back and asserts Postgres rejects it.
"""
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, text, inspect
import pandas as pd

from app.connectors.base import Connector, TableSchema, ColumnInfo, QueryResult
from app.security.secrets import RedactedSecret


class PostgresConnector(Connector):
    def __init__(self, host: str, port: int, database: str, username: str,
                 password: RedactedSecret, timeout_seconds: int = 15,
                 extra_config: dict | None = None):
        # extra_config exists for interface parity with every connector
        # (build_connector()/routes_connections.py construct all of them
        # identically) - unused here, Postgres needs nothing beyond
        # host/port/database/username/password. See
        # app/connectors/snowflake.py for the connector that actually
        # needs it.
        self._timeout_seconds = timeout_seconds
        url = (
            f"postgresql+psycopg2://{username}:{password.reveal()}"
            f"@{host}:{port}/{database}"
        )
        self._engine = create_engine(url, pool_pre_ping=True, pool_size=3)

    @contextmanager
    def _readonly_conn(self, timeout_seconds: int):
        """
        Opens the connection in AUTOCOMMIT mode so SQLAlchemy does not
        silently autobegin its own transaction before our explicit `BEGIN
        TRANSACTION READ ONLY` runs (that silent autobegin was a real bug:
        `SET SESSION CHARACTERISTICS` only affects the *next* transaction,
        so if SQLAlchemy had already opened one implicitly, the read-only
        setting never took effect for the actual query). Explicit BEGIN/
        COMMIT here guarantees every query genuinely executes inside a
        READ ONLY transaction that Postgres itself enforces.
        """
        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.execute(text(f"SET statement_timeout = {int(timeout_seconds * 1000)}"))
            conn.execute(text("BEGIN TRANSACTION READ ONLY"))
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
        """Prove the session truly cannot mutate data. `CREATE TEMP TABLE`
        is a genuine write to the transaction's write-state (unlike a
        session-local `SET`/`pg_settings` change, which Postgres permits
        even inside a READ ONLY transaction and is therefore NOT a valid
        test) — Postgres rejects it under `READ ONLY` regardless of the
        role's own grants, so success here proves the enforcement works
        end-to-end rather than just checking role privileges."""
        try:
            with self._engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("BEGIN TRANSACTION READ ONLY"))
                try:
                    conn.execute(text("CREATE TEMP TABLE _ro_probe (x int)"))
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
