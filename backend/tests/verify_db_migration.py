"""
Throwaway verification for scripts/migrate_metadata_db.py - the SQLite ->
Postgres metadata migration.

Real Postgres isn't available in this environment, so the target here is a
second SQLite file. That still exercises the parts that can go wrong:
FK-safe table ordering, every row copied, --force behaviour, and - the
important one - the audit hash chain still verifying on the target, which
only holds if the JSON `detail` column round-tripped as a dict and row
order was preserved. (On real Postgres, SQLAlchemy's JSON type is what
makes the dict come back a dict; on SQLite both ends are TEXT.)

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_db_migration.py
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Base, Tenant, User, DataSourceConnection, Conversation, QueryRecord, Notification,
)
from app.audit import logger as audit
from scripts.migrate_metadata_db import migrate

SRC = f"sqlite:///{os.path.join(_tmp, 'source.db')}"
DST = f"sqlite:///{os.path.join(_tmp, 'target.db')}"

# ---- build a representative source DB -------------------------------------
src_engine = create_engine(SRC, connect_args={"check_same_thread": False})
Base.metadata.create_all(src_engine)

with Session(src_engine) as s:
    for n in range(2):
        t = Tenant(name=f"Tenant {n}", subdomain=f"tenant-{n}", subscription_status="active")
        s.add(t); s.flush()
        u = User(tenant_id=t.id, email=f"admin{n}@t{n}.test", role="admin",
                 password_hash="pbkdf2_sha256$600000$abc$def",
                 row_scope={"region": ["South-East", "North-West"]})
        s.add(u)
        conn = DataSourceConnection(
            tenant_id=t.id, name="warehouse", kind="postgres", host="db.internal",
            port=5432, database="analytics", username="ro",
            encrypted_password="gAAAAAB-fake-fernet-ciphertext-value-here==",
            table_allowlist=["sales", "customers"],
            column_policy={"sales": ["region", "revenue", "month"]},
        )
        s.add(conn); s.flush()
        c = Conversation(tenant_id=t.id, user_id=u.id, connection_id=conn.id,
                         context={"table": "sales", "dimensions": ["region"]})
        s.add(c); s.flush()
        s.add(QueryRecord(tenant_id=t.id, user_id=u.id, connection_id=conn.id,
                          conversation_id=c.id, question="why did revenue fall",
                          generated_sql="SELECT ...", row_count=12, duration_ms=340,
                          result_snapshot={"metrics": {"total": 1000}, "anomalies": []}))
        s.add(Notification(tenant_id=t.id, user_id=u.id, kind="subscription_activated",
                           title="Subscription active", body="Pro is now active", link="/billing"))
        s.commit()
        # real audit rows so the hash chain is genuine (detail is a dict)
        for i in range(4):
            audit.log(s, t.id, "query_executed", u.id, connection_id=conn.id,
                      detail={"rows": 12 + i, "table": "sales"})
        audit.log(s, t.id, "connection_created", u.id, detail={"kind": "postgres"})

with src_engine.connect() as c:
    src_total = {t.name: c.execute(select(func.count()).select_from(t)).scalar()
                 for t in Base.metadata.sorted_tables}
print("source row counts:", {k: v for k, v in src_total.items() if v})

# ---- 1. migrate to an empty target --------------------------------------
rc = migrate(SRC, DST)
assert rc == 0, f"migrate() returned {rc}"
print("1. OK  migrate() -> 0")

dst_engine = create_engine(DST, connect_args={"check_same_thread": False})
with dst_engine.connect() as c:
    for t in Base.metadata.sorted_tables:
        s_n = src_total[t.name]
        d_n = c.execute(select(func.count()).select_from(t)).scalar()
        assert s_n == d_n, f"{t.name}: source {s_n} != target {d_n}"
print("2. OK  every table's row count matches on the target")

# audit chain must verify on the target (proves detail round-tripped as a
# dict and row order held)
from app.db.models import AuditLog
with Session(dst_engine) as ds:
    tids = [r[0] for r in ds.execute(select(AuditLog.tenant_id).distinct())]
    assert len(tids) == 2, tids
    for tid in tids:
        res = audit.verify_chain(ds, tid)
        assert res["intact"], f"chain broken for {tid}: {res}"
        assert res["checked"] == 5, res
print("3. OK  audit hash chain intact on the target for both tenants")

# spot-check a JSON column and the encrypted credential came across verbatim
with Session(dst_engine) as ds:
    u = ds.query(User).first()
    assert u.row_scope == {"region": ["South-East", "North-West"]}, u.row_scope
    conn = ds.query(DataSourceConnection).first()
    assert conn.encrypted_password == "gAAAAAB-fake-fernet-ciphertext-value-here=="
    assert conn.column_policy == {"sales": ["region", "revenue", "month"]}
print("4. OK  JSON columns are dicts, encrypted_password copied byte-for-byte")

# ---- 2. re-run without --force -> refuses ------------------------------
rc = migrate(SRC, DST)
assert rc == 1, f"expected refusal (1), got {rc}"
print("5. OK  re-run without --force -> refuses (target not empty)")

# ---- 3. --force wipes and reloads, still consistent ------------------
rc = migrate(SRC, DST, force=True)
assert rc == 0, f"--force run returned {rc}"
with dst_engine.connect() as c:
    for t in Base.metadata.sorted_tables:
        assert c.execute(select(func.count()).select_from(t)).scalar() == src_total[t.name]
print("6. OK  --force wipes and reloads cleanly, counts still match")

print("\nALL CHECKS PASSED")
