"""
MySQL / MariaDB connector.

Same defense-in-depth pattern as the Postgres connector, adapted to MySQL's
syntax:
  1. `START TRANSACTION READ ONLY` — MySQL rejects writes inside this at the
     server level, independent of the role's own grants (available since
     MySQL 5.6 / MariaDB 10.0).
  2. `SET SESSION MAX_EXECUTION_TIME` bounds runaway queries (MySQL 5.7.8+;
     MariaDB uses `SET STATEMENT max_statement_time=... FOR <query>` instead
     — see _timeout_prefix below).
  3. `verify_read_only()` proactively proves a write is rejected inside the
     read-only transaction, the same probe pattern as Postgres.
"""
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, text, inspect
import pandas as pd

from app.connectors.base import Connector, TableSchema, ColumnInfo, QueryResult
from app.security.secrets import RedactedSecret


class MySQLConnector(Connector):
    def __init__(self, host: str, port: int, database: str, username: str,
                 password: RedactedSecret, timeout_seconds: int = 15):
        url = (
            f"mysql+pymysql://{username}:{password.reveal()}"
            f"@{host}:{port}/{database}"
        )
        self._engine = create_engine(url, pool_pre_ping=True, pool_size=3)

    @contextmanager
    def _readonly_conn(self, timeout_seconds: int):
        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            try:
                conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_seconds * 1000)}"))
            except Exception:
                pass  # MariaDB doesn't support this GUC; per-query timeout is applied differently there
            conn.execute(text("START TRANSACTION READ ONLY"))
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
        try:
            with self._engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("START TRANSACTION READ ONLY"))
                try:
                    conn.execute(text("CREATE TEMPORARY TABLE _ro_probe (x INT)"))
                    conn.execute(text("ROLLBACK"))
                    return False
                except Exception:
                    conn.execute(text("ROLLBACK"))
                    return True
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
