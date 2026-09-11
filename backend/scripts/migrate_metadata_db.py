"""
One-off: copy the whole metadata DB from SQLite to Postgres, table by
table, then verify. READ-ONLY on the source - safe to re-run.

Why a script and not `pgloader`: this schema stores several columns as
JSON (audit `detail`, row scopes, policies, ...). Going through
SQLAlchemy's own column types - the same ones the app uses - guarantees a
dict written on SQLite comes back a dict on Postgres, which the audit
hash-chain verification depends on. A raw dump/load would leave them as
strings on Postgres and every `verify_chain` would fail.

Run it as a Railway one-off on the BACKEND service (it needs the SQLite
volume AND network access to the new Postgres):

    TARGET_DB_URL='postgresql://...the new Railway Postgres URL...' \
    python scripts/migrate_metadata_db.py

SOURCE_DB_URL defaults to METADATA_DB_URL (the SQLite file the app is
using right now). Add --force to wipe and reload a target that already
has rows.

After it succeeds and reports the audit chains intact: set
METADATA_DB_URL on the backend to the Postgres URL, remove this one-off
command, redeploy. Keep APP_SECRET_KEY unchanged - the stored connection
credentials are still encrypted with it.
"""
import os
import sys

# Make `app` importable no matter where this is launched from. A plain
# `python scripts/migrate_metadata_db.py` only puts scripts/ on sys.path,
# not the backend root - so add it (this file is backend/scripts/x.py).
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

# app.db.models / app.audit.logger pull in only SQLAlchemy + stdlib - no
# app.config, so this runs without APP_SECRET_KEY etc.
from app.db.models import AuditLog, Base
from app.audit.logger import verify_chain

CHUNK = 500


def _normalise(url: str) -> str:
    # Railway/Heroku hand out the legacy scheme; SQLAlchemy needs the
    # modern dialect name (same fix app/db/session.py applies).
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def migrate(source_url: str, target_url: str, force: bool = False) -> int:
    """The copy + verify, factored out so tests can drive it directly.
    Returns 0 on success, 1 if anything didn't line up."""
    source_url = _normalise(source_url)
    target_url = _normalise(target_url)

    src = create_engine(
        source_url,
        connect_args={"check_same_thread": False} if source_url.startswith("sqlite") else {},
    )
    dst = create_engine(target_url)

    print(f"source: {source_url}")
    print(f"target: {target_url.split('@')[-1] if '@' in target_url else target_url}\n")

    # 1. schema on the fresh target. On a brand-new Postgres, create_all
    #    makes every column (including JSON as native json) - the light
    #    migrations in session.py only matter for ALTERing an existing DB.
    Base.metadata.create_all(dst)
    tables = list(Base.metadata.sorted_tables)  # FK-safe parent-first order

    # 2. is the target already populated?
    with dst.connect() as c:
        populated = [t.name for t in tables if c.execute(select(func.count()).select_from(t)).scalar()]
    if populated:
        if not force:
            print(
                f"target already has rows in: {', '.join(populated)}\n"
                f"re-run with --force to wipe and reload."
            )
            return 1
        print(f"--force: clearing {len(populated)} non-empty table(s) on target")
        with dst.begin() as c:
            for t in reversed(tables):
                c.execute(t.delete())

    # 3. copy, parent tables first
    print("copying:")
    counts: dict[str, tuple[int, int]] = {}
    with src.connect() as sc, dst.begin() as dc:
        for t in tables:
            rows = [dict(r._mapping) for r in sc.execute(select(t))]
            for i in range(0, len(rows), CHUNK):
                dc.execute(t.insert(), rows[i:i + CHUNK])
            counts[t.name] = (len(rows), 0)
            print(f"  {t.name:26} {len(rows):>6}")

    # 4. verify row counts
    print("\nverifying row counts:")
    mismatch = False
    with src.connect() as sc, dst.connect() as dc:
        for t in tables:
            s = sc.execute(select(func.count()).select_from(t)).scalar()
            d = dc.execute(select(func.count()).select_from(t)).scalar()
            flag = "" if s == d else "  <-- MISMATCH"
            if s != d:
                mismatch = True
            print(f"  {t.name:26} source={s:>6}  target={d:>6}{flag}")

    # 5. verify the audit hash chain per tenant on the target
    print("\nverifying audit hash chains on target:")
    chain_broken = False
    with Session(dst) as ds:
        tenant_ids = [r[0] for r in ds.execute(select(AuditLog.tenant_id).distinct())]
        if not tenant_ids:
            print("  (no audit rows)")
        for tid in tenant_ids:
            res = verify_chain(ds, tid)
            state = "intact" if res["intact"] else f"BROKEN at {res['broken_at']} - {res['reason']}"
            if not res["intact"]:
                chain_broken = True
            print(f"  tenant {tid[:8]}...  {res['checked']:>5} rows  {state}")

    print()
    if mismatch or chain_broken:
        print("MIGRATION HAS PROBLEMS - do not cut over. See the mismatches above.")
        return 1
    print("OK - all tables copied, counts match, audit chains intact.")
    print("Next: point METADATA_DB_URL at the Postgres URL and redeploy.")
    return 0


def main() -> int:
    source_url = os.environ.get("SOURCE_DB_URL") or os.environ.get("METADATA_DB_URL", "")
    target_url = os.environ.get("TARGET_DB_URL", "")
    if not source_url:
        sys.exit("Set SOURCE_DB_URL (or METADATA_DB_URL) to the current SQLite DB.")
    if not target_url:
        sys.exit("Set TARGET_DB_URL to the new Postgres URL.")
    if not _normalise(source_url).startswith("sqlite"):
        print(f"note: source is not sqlite ({source_url.split(':')[0]}) - continuing anyway")
    if _normalise(target_url).startswith("sqlite"):
        sys.exit("TARGET_DB_URL looks like SQLite - refusing. This migrates TO Postgres.")
    return migrate(source_url, target_url, force="--force" in sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
