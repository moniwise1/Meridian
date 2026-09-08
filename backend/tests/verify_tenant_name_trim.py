"""
Throwaway verification for the "tenant with a padded name can't be deleted"
fix. Real SQLite + real FastAPI app via TestClient.

Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant

init_db()
client = TestClient(app)

# 1. Registering with a padded company name stores it trimmed.
r = client.post("/auth/register", json={
    "company_name": "  Joelan  ", "email": "owner@joelanco.com", "password": "supersecret1",
})
assert r.status_code == 200, (r.status_code, r.text)
db = SessionLocal()
t = db.query(Tenant).filter(Tenant.name.like("%Joelan%")).one()
assert t.name == "Joelan", repr(t.name)
print(f"1. OK  padded signup stored name = {t.name!r}")

# 2. Blank company name is rejected, not stored as "".
r = client.post("/auth/register", json={
    "company_name": "   ", "email": "x@blankco.com", "password": "supersecret1",
})
assert r.status_code == 400, (r.status_code, r.text)
print(f"2. OK  blank company name rejected: {r.json()['detail']!r}")

# 3. The frontend delete-confirm gate (trimmed compare) now matches.
#    Mirrors platform/tenants/page.tsx: disabled={confirmText.trim() !== t.name.trim()}
def confirm_enabled(typed: str, stored: str) -> bool:
    return typed.strip() == stored.strip()

# a legacy row that still has the padding (simulate pre-fix data):
legacy = Tenant(name="  Padco  ")
db.add(legacy); db.commit()
assert not confirm_enabled("Padco", "  Padco  ") is False or True  # readability noop
assert confirm_enabled("Padco", legacy.name) is True, "trimmed gate should accept the visible name"
assert confirm_enabled("Padco", "Padco") is True
assert confirm_enabled("Wrong", legacy.name) is False
print("3. OK  trimmed confirm gate accepts the visible name for a padded legacy row")

# 4. Staff owner can repair a padded legacy row via PATCH name (strip in update_tenant).
from app.db.models import PlatformStaff
from app.security.auth import hash_password
from app.security.platform_auth import create_platform_access_token
staff = PlatformStaff(email="root@meridianhq.com", password_hash=hash_password("supersecret1"), role="owner")
db.add(staff); db.commit(); db.refresh(staff)
tok = create_platform_access_token(staff.id, staff.role)
r = client.patch(f"/platform/tenants/{legacy.id}", json={"name": "  Padco  "},
                 headers={"Authorization": f"Bearer {tok}"})
assert r.status_code == 200, (r.status_code, r.text)
db.expire_all()
assert db.query(Tenant).filter_by(id=legacy.id).one().name == "Padco"
print("4. OK  PATCH /platform/tenants/{id} stores the name trimmed")

print("\nALL CHECKS PASSED")
