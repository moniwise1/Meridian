from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db.models import Base

# Managed Postgres providers (Railway, Heroku, and others) commonly hand out
# a connection string with the legacy "postgres://" scheme. SQLAlchemy 1.4+
# only recognizes the "postgresql://" dialect name and raises
# NoSuchModuleError on the old one, so normalize it here rather than making
# every deployment target remember to do it in their own env var.
_db_url = settings.metadata_db_url
if _db_url.startswith("postgres://"):
    _db_url = "postgresql://" + _db_url[len("postgres://"):]

engine = create_engine(
    _db_url,
    connect_args={"check_same_thread": False} if _db_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# (table, column, SQL type) added to an existing model after its table may
# already have been created elsewhere (a dev machine, a deployed instance).
# There's no Alembic in this project - `Base.metadata.create_all` only ever
# creates missing TABLES, never adds a missing COLUMN to one that already
# exists, so a plain new `Column(...)` on an existing model would silently
# do nothing on any database that predates it and then blow up the first
# time it's read or written. Each entry here is applied with a plain
# `ADD COLUMN` exactly once, tracked by checking whether the column
# already exists - safe to run on every boot, including a totally fresh
# database where create_all just made the column already exist and every
# entry here becomes a no-op.
#
# The SQL type can be a plain string (used for every dialect) or a dict of
# {dialect_name: type}, with "default" as the fallback for any dialect not
# listed. A JSON-typed model column NEEDS this: a bare `Column(JSON, ...)`
# on Postgres is only correctly read back as a dict by SQLAlchemy's own
# JSON type when the underlying column is genuinely Postgres's native
# `json` type - a generic `TEXT` column silently accepts the write (the
# serialized string goes in fine) but comes back as a raw string on read,
# not a parsed dict, since the JSON-aware bind/result processing SQLAlchemy
# applies is tied to the dialect recognizing the column as JSON, not just
# to the Python-side column type. Caught by actually reading a value back
# after writing it through a migrated column, against real Postgres, not
# by reasoning about it in the abstract - see the git history for the
# specific real regression this fixed before it ever reached production.
_ADDED_COLUMNS = [
    ("users", "created_at", "TIMESTAMP"),
    ("tenants", "subscription_expires_at", "TIMESTAMP"),
    ("data_source_connections", "extra_config", {"postgresql": "JSON", "mysql": "JSON", "default": "TEXT"}),
    ("tenants", "plan", "VARCHAR"),
    ("uploaded_documents", "ocr_pages_used", "INTEGER"),
]


def _run_light_migrations() -> None:
    inspector = inspect(engine)
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            if isinstance(sql_type, dict):
                sql_type = sql_type.get(dialect, sql_type["default"])
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))


def init_db():
    Base.metadata.create_all(engine)
    _run_light_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
