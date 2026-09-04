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
    ("tenants", "require_mfa", "BOOLEAN DEFAULT FALSE"),
    ("users", "totp_secret", "TEXT"),
    ("users", "totp_enabled", "BOOLEAN DEFAULT FALSE"),
    ("tenants", "subdomain", "VARCHAR"),
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

        # A plain ADD COLUMN can't carry a UNIQUE constraint along with it
        # portably across SQLite/Postgres in one statement - added as its
        # own idempotent step. NULLs don't collide with each other under a
        # unique index (standard SQL behavior), so this is safe to create
        # before the backfill below has run on every existing row yet.
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_subdomain ON tenants (subdomain)"
        ))


def _backfill_tenant_subdomains() -> None:
    """Every tenant created before this feature existed has subdomain=NULL
    - since a subdomain is now a real login boundary (see
    routes_auth.py's login()), a tenant stuck without one would have no
    way to use it at all. Runs on every boot; a no-op once every tenant
    has one."""
    from app.db.models import Tenant
    from app.tenant_slug import generate_unique_subdomain

    db = SessionLocal()
    try:
        missing = db.query(Tenant).filter(Tenant.subdomain.is_(None)).all()
        for tenant in missing:
            tenant.subdomain = generate_unique_subdomain(db, tenant.name)
            # generate_unique_subdomain's collision check queries the DB -
            # without flushing, two tenants with the same name IN THIS
            # SAME BATCH (real case: leftover same-named test tenants)
            # wouldn't see each other's not-yet-flushed assignment and
            # could both compute the identical "unique" subdomain, only
            # to collide for real at commit. Caught live, not assumed.
            db.flush()
        if missing:
            db.commit()
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(engine)
    _run_light_migrations()
    _backfill_tenant_subdomains()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
