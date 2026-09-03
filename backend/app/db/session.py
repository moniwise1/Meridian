from sqlalchemy import create_engine
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


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
