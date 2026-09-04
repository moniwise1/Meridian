"""
Snowflake connector.

Snowflake's connection model doesn't map onto the same host:port shape
the other three connectors use — there's no host or port in the usual
sense, just an account identifier, and a query additionally needs a
*warehouse* (Snowflake's unit of compute) to run against at all, plus an
optional *role* to pick which of the credential's granted roles the
session uses. None of DataSourceConnection's other columns had anywhere
to put those, so this is the first connector to use `extra_config`
(app/db/models.py, a JSON blob added specifically for connector-specific
parameters that don't generalize): `host` holds the account identifier
(structurally the closest fit to what "host" means for every other
connector here), `extra_config` holds
`{"warehouse": "...", "schema": "..." (optional, defaults PUBLIC),
"role": "..." (optional)}`. `port` is accepted for interface parity with
every other connector (build_connector()/routes_connections.py construct
all connectors identically) but genuinely unused — Snowflake's driver has
no concept of one.

Technical read-only enforcement here is honestly weaker than Postgres/
MySQL/MSSQL's, not glossed over as equivalent: Snowflake has no
session-level READ ONLY transaction pragma the way those three do (no
`BEGIN TRANSACTION READ ONLY` equivalent), so there's no independent,
universal backstop. verify_read_only() instead attempts a real write
(`CREATE TEMPORARY TABLE`, then drops it if it somehow succeeded) and
relies entirely on the connected role's own grants to reject it — a
genuine technical probe (an actual write attempt, actually rejected by
the server, not just a documentation promise), but its correctness is
only as strong as the role really having no write grants, with no second
independent layer catching a misconfigured role the way the other three
connectors have. Setup instructions for this connector should say so
explicitly: create a role with USAGE + SELECT only, nothing else, and
confirm that manually in Snowflake before connecting it here.

Unverified against a live Snowflake account — none available in this
environment. Built strictly to snowflake-sqlalchemy's documented
connection-string/session-parameter contract, the same category of
caveat already given for app/billing/paystack.py. Confirm the first real
connection actually round-trips (test_connection, verify_read_only, a
real query) before trusting this in production.
"""
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, text, inspect
import pandas as pd

from app.connectors.base import Connector, TableSchema, ColumnInfo, QueryResult
from app.security.secrets import RedactedSecret


class SnowflakeConnector(Connector):
    def __init__(self, host: str, port: int, database: str, username: str,
                 password: RedactedSecret, timeout_seconds: int = 15,
                 extra_config: dict | None = None):
        extra_config = extra_config or {}
        warehouse = extra_config.get("warehouse")
        if not warehouse:
            raise ValueError(
                "Snowflake connections require a warehouse — set extra_config.warehouse "
                "to the name of the warehouse this credential should run queries on.",
            )
        schema = extra_config.get("schema") or "PUBLIC"
        role = extra_config.get("role")

        url = f"snowflake://{username}:{password.reveal()}@{host}/{database}/{schema}?warehouse={warehouse}"
        if role:
            url += f"&role={role}"
        self._engine = create_engine(url)

    @contextmanager
    def _timed_conn(self, timeout_seconds: int):
        """No READ ONLY transaction mode to open here (see module
        docstring) - this just applies the query timeout. Snowflake
        autocommits each statement by default (no implicit multi-
        statement transaction the way Postgres/MySQL sessions get), so
        there's no BEGIN/COMMIT/ROLLBACK bracket needed either."""
        conn = self._engine.connect()
        try:
            conn.execute(text(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {int(timeout_seconds)}"))
            yield conn
        finally:
            conn.close()

    def test_connection(self) -> bool:
        try:
            with self._timed_conn(5) as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def verify_read_only(self) -> bool:
        try:
            with self._engine.connect() as conn:
                try:
                    conn.execute(text("CREATE TEMPORARY TABLE _ro_probe (x INT)"))
                    conn.execute(text("DROP TABLE _ro_probe"))
                    return False  # the write succeeded -> not safely read-only
                except Exception:
                    return True  # the write was rejected, as required
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
        with self._timed_conn(timeout_seconds) as conn:
            df = pd.read_sql(text(sql), conn)
        truncated = len(df) >= row_limit
        duration_ms = int((time.time() - start) * 1000)
        return QueryResult(dataframe=df, duration_ms=duration_ms, truncated=truncated)
