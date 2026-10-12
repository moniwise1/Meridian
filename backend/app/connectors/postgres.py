"""
PostgreSQL connector.

Technical (not just policy) read-only enforcement:
  1. Every session opens with `SET SESSION CHARACTERISTICS AS TRANSACTION
     READ ONLY`, so even if the underlying role somehow had write grants,
     the session itself cannot commit a mutation.
  2. `statement_timeout` is set per-connection to bound runaway queries.
  3. `verify_read_only()` checks effective role, schema, table and column
     privileges without issuing any write or DDL probe.
"""
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import URL
import pandas as pd

from app.connectors.base import Connector, TableSchema, ColumnInfo, QueryResult
from app.security.secrets import RedactedSecret


class PostgresConnector(Connector):
    def __init__(self, host: str, port: int, database: str, username: str,
                 password: RedactedSecret, timeout_seconds: int = 15,
                 extra_config: dict | None = None):
        self._timeout_seconds = timeout_seconds
        url = URL.create("postgresql+psycopg2", username=username, password=password.reveal(),
                         host=host, port=port, database=database)
        options = {}
        if (extra_config or {}).get("transport_tls") == "verify":
            import ssl
            ca_file = ssl.get_default_verify_paths().cafile
            if not ca_file:
                raise ValueError("No system certificate authority bundle is available for verified TLS.")
            options = {"sslmode": "verify-full", "sslrootcert": ca_file, "connect_timeout": 10}
        self._engine = create_engine(url, pool_pre_ping=True, pool_size=3, connect_args=options)

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
        """Inspect effective privileges without attempting a write to the customer's DB."""
        try:
            with self._readonly_conn(5) as conn:
                if conn.execute(text("SHOW transaction_read_only")).scalar() != "on":
                    return False
                elevated = conn.execute(text("""
                    SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user
                        AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls))
                """)).scalar()
                writable = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind IN ('r','p','v','m','f')
                        AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                        AND (has_table_privilege(current_user, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')
                            OR has_any_column_privilege(current_user, c.oid, 'INSERT,UPDATE'))
                    ) OR EXISTS (
                        SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%'
                        AND n.nspname <> 'information_schema'
                        AND has_schema_privilege(current_user, n.oid, 'CREATE')
                    )
                """)).scalar()
                return not bool(elevated or writable)
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

    def run_query(self, sql: str, row_limit: int, timeout_seconds: int, params: dict | None = None) -> QueryResult:
        start = time.time()
        with self._readonly_conn(timeout_seconds) as conn:
            df = pd.read_sql(text(sql), conn, params=params)
        truncated = len(df) >= row_limit
        duration_ms = int((time.time() - start) * 1000)
        return QueryResult(dataframe=df, duration_ms=duration_ms, truncated=truncated)
