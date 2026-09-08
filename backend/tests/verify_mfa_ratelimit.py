"""
Throwaway verification for security fix #10 — self-service MFA /confirm and
/disable must be rate-limited like the login-time code checks.
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["LOGIN_FREE_ATTEMPTS"] = "5"

import pyotp
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User
from app.security.auth import hash_password, create_access_token
from app.security import login_cooldown

init_db()
client = TestClient(app)
db = SessionLocal()
t = Tenant(name="Acme"); db.add(t); db.flush()
u = User(tenant_id=t.id, email="a@acmeco.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
H = {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def reset_cooldown():
    login_cooldown._mfa_login_guard.record_success(u.id)


# --- enrol MFA ---
r = client.post("/auth/mfa/setup", headers=H); assert r.status_code == 200, r.text
secret = r.json()["secret"]
r = client.post("/auth/mfa/confirm", headers=H, json={"code": pyotp.TOTP(secret).now()})
assert r.status_code == 200 and r.json()["enabled"] is True, r.text
print("1. OK  MFA enrolled")

# --- /disable: 5 wrong codes cost nothing, the 6th is throttled (429) ---
reset_cooldown()
codes = [str((i * 111111 + 1) % 1000000).zfill(6) for i in range(5)]
for i, c in enumerate(codes, 1):
    r = client.post("/auth/mfa/disable", headers=H, json={"code": c})
    assert r.status_code == 400, (i, r.status_code, r.text)   # wrong code, not yet throttled
r = client.post("/auth/mfa/disable", headers=H, json={"code": "000000"})
assert r.status_code == 429, (r.status_code, r.text)
print("2. OK  /disable throttles after 5 wrong codes (6th -> 429)")

# --- a correct code is NEVER hard-locked: clear + succeed ---
reset_cooldown()
r = client.post("/auth/mfa/disable", headers=H, json={"code": pyotp.TOTP(secret).now()})
assert r.status_code == 200 and r.json()["enabled"] is False, r.text
print("3. OK  correct code still disables MFA (never a permanent lockout)")

# --- /confirm is rate-limited too ---
r = client.post("/auth/mfa/setup", headers=H); secret2 = r.json()["secret"]
reset_cooldown()
for i in range(5):
    r = client.post("/auth/mfa/confirm", headers=H, json={"code": "010101"})
    assert r.status_code == 400, (i, r.status_code, r.text)
r = client.post("/auth/mfa/confirm", headers=H, json={"code": "020202"})
assert r.status_code == 429, (r.status_code, r.text)
print("4. OK  /confirm throttles after 5 wrong codes (6th -> 429)")

# --- and a real code still confirms after a reset ---
reset_cooldown()
r = client.post("/auth/mfa/confirm", headers=H, json={"code": pyotp.TOTP(secret2).now()})
assert r.status_code == 200 and r.json()["enabled"] is True, r.text
print("5. OK  correct code still confirms MFA")

print("\nALL CHECKS PASSED")
