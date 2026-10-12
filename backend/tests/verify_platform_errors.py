"""
Throwaway verification for GET /platform/errors - the drill-down behind
the platform Dashboard's "Errors, last hour" count.
Real SQLite + FastAPI TestClient. Run from backend/:
  PYTHONPATH=$(pwd) python tests/verify_platform_errors.py
"""
import base64, os, tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, AuditLog, PlatformStaff
from app.security.auth import hash_password
from app.security.platform_auth import create_platform_access_token

init_db()
client = TestClient(app)
db = SessionLocal()

acme = Tenant(name="Acme Co", subscription_status="active")
other = Tenant(name="Other Co", subscription_status="active")
db.add_all([acme, other]); db.commit()

now = datetime.utcnow()


def row(tenant_id, status, action, when, detail=None):
    db.add(AuditLog(tenant_id=tenant_id, action=action, status=status,
                    detail=detail or {}, timestamp=when))


row(acme.id, "error", "query_failed", now - timedelta(minutes=5), {"reason": "timeout"})
row(acme.id, "ok", "query_executed", now - timedelta(minutes=5))  # not an error - excluded
row(other.id, "error", "connection_check_failed", now - timedelta(minutes=30), {"host": "db.internal"})
row("platform", "error", "staff_login_failed", now - timedelta(minutes=10))
row("no-such-tenant-id", "error", "artifact_generation_failed", now - timedelta(minutes=1))
row(acme.id, "error", "query_failed", now - timedelta(hours=2))  # outside the 1h window
db.commit()

staff = PlatformStaff(email="owner@meridian.test", password_hash=hash_password("supersecret1"), role="owner")
db.add(staff); db.commit()
H = {"Authorization": f"Bearer {create_platform_access_token(staff.id, staff.role)}"}

# --- A. no auth -> 401 ---
r = client.get("/platform/errors")
assert r.status_code == 401, (r.status_code, r.text)
print("1. OK  no staff auth -> 401")

# --- B. default 1h window: 4 errors, not the 'ok' row, not the 2h-old one ---
r = client.get("/platform/errors", headers=H)
assert r.status_code == 200, (r.status_code, r.text)
rows = r.json()
assert len(rows) == 4, [x["action"] for x in rows]
actions = {x["action"] for x in rows}
assert "query_executed" not in actions, "the ok-status row leaked in"
assert actions == {
    "query_failed", "connection_check_failed", "staff_login_failed", "artifact_generation_failed",
}, actions
print(f"2. OK  1h window -> {len(rows)} errors, ok-status row excluded, 2h-old row excluded")

# --- C. tenant names resolved correctly ---
by_action = {x["action"]: x for x in rows}
assert by_action["query_failed"]["tenant_name"] == "Acme Co", by_action["query_failed"]
assert by_action["connection_check_failed"]["tenant_name"] == "Other Co"
assert by_action["staff_login_failed"]["tenant_name"] == "Platform"
assert by_action["artifact_generation_failed"]["tenant_name"] == "Deleted tenant"
print("3. OK  tenant_name resolved: real tenants by name, 'platform' -> Platform, unknown -> Deleted tenant")

# --- D. detail passed through ---
assert by_action["query_failed"]["detail"] == {"reason": "timeout"}
print("4. OK  detail passed through")

# --- E. wider window picks up the 2h-old row too ---
r = client.get("/platform/errors?hours=24", headers=H)
rows24 = r.json()
assert len(rows24) == 5, [x["action"] for x in rows24]
print(f"5. OK  24h window -> {len(rows24)} errors (includes the 2h-old one)")

# --- F. hours is clamped, not a way to bypass sane limits ---
r = client.get("/platform/errors?hours=999999", headers=H)
assert r.status_code == 200, (r.status_code, r.text)
print("6. OK  a huge hours value doesn't error (clamped server-side)")

print("\nALL CHECKS PASSED")
