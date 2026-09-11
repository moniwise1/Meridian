"""
Throwaway verification for self-service account settings: display name,
the one-lifetime-change email update, and password change (current-
password verification required for both of the last two).
Real SQLite + FastAPI TestClient. Run from backend/:
  PYTHONPATH=$(pwd) python tests/verify_account_self_service.py
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User
from app.security.auth import hash_password, create_access_token

init_db()
client = TestClient(app)
db = SessionLocal()

t = Tenant(name="Acme Co", subscription_status="none")
db.add(t); db.flush()
u = User(tenant_id=t.id, email="founder@acme.example.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
H = {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}

# --- A. /me starts with no display name, email change available ---
r = client.get("/auth/me", headers=H)
assert r.status_code == 200, (r.status_code, r.text)
me = r.json()
assert me["display_name"] is None and me["email_change_available"] is True, me
print("1. OK  fresh account: no display name, email change available")

# --- B. set a display name ---
r = client.patch("/auth/me/display-name", json={"display_name": "  Founder Joe  "}, headers=H)
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["display_name"] == "Founder Joe", r.json()  # trimmed
print("2. OK  display name set (trimmed)")

# --- C. clear it back with a blank string ---
r = client.patch("/auth/me/display-name", json={"display_name": "   "}, headers=H)
assert r.json()["display_name"] is None, r.json()
print("3. OK  blank display name clears it back to null")

# --- D. wrong current password blocks both email and password change ---
r = client.patch("/auth/me/email", json={"new_email": "new@acme.example.com", "current_password": "wrongpass"}, headers=H)
assert r.status_code == 401, (r.status_code, r.text)
r = client.patch("/auth/me/password", json={"current_password": "wrongpass", "new_password": "newpassword1"}, headers=H)
assert r.status_code == 401, (r.status_code, r.text)
print("4. OK  wrong current password blocks email and password change")

# --- E. real email change works once ---
r = client.patch("/auth/me/email", json={"new_email": "NEW@Acme.example.com", "current_password": "supersecret1"}, headers=H)
assert r.status_code == 200, (r.status_code, r.text)
body = r.json()
assert body["email"] == "new@acme.example.com" and body["email_change_available"] is False, body  # normalized lowercase
print("5. OK  email changed once, normalized lowercase, email_change_available flips false")

# --- F. a second change is refused, even with the right password ---
r = client.patch("/auth/me/email", json={"new_email": "third@acme.example.com", "current_password": "supersecret1"}, headers=H)
assert r.status_code == 400 and "once" in r.json()["detail"].lower(), (r.status_code, r.text)
print("6. OK  second email change refused - one per lifetime")

# --- G. can't change email to one already in use ---
other_user = User(tenant_id=t.id, email="taken@acme.example.com", role="analyst", password_hash=hash_password("otherpass1"))
db.add(other_user); db.commit()
# founder already used their change (F above) - use a fresh account to test the collision check itself
u2 = User(tenant_id=t.id, email="second@acme.example.com", role="analyst", password_hash=hash_password("secondpass1"))
db.add(u2); db.commit()
H2 = {"Authorization": f"Bearer {create_access_token(u2.id, t.id, u2.role)}"}
r = client.patch("/auth/me/email", json={"new_email": "taken@acme.example.com", "current_password": "secondpass1"}, headers=H2)
assert r.status_code == 400 and "already exists" in r.json()["detail"], (r.status_code, r.text)
print("7. OK  can't change email to one another user already has")

# --- H. password change works, and the new password actually logs in ---
r = client.patch("/auth/me/password", json={"current_password": "secondpass1", "new_password": "brandnewpass1"}, headers=H2)
assert r.status_code == 200, (r.status_code, r.text)
r = client.post("/auth/login", json={"email": "second@acme.example.com", "password": "brandnewpass1"})
assert r.status_code == 200 and r.json().get("access_token"), (r.status_code, r.text)
r = client.post("/auth/login", json={"email": "second@acme.example.com", "password": "secondpass1"})
assert r.status_code == 401, "old password should no longer work"
print("8. OK  password change takes effect - new password logs in, old one doesn't")

print("\nALL CHECKS PASSED")
