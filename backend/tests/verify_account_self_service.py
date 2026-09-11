"""
Throwaway verification for self-service account settings: display name
(60-day cooldown between changes), the one-lifetime-change email update,
and password change (current-password verification required for both of
the last two).
Real SQLite + FastAPI TestClient. Run from backend/:
  PYTHONPATH=$(pwd) python tests/verify_account_self_service.py
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

# --- A. /me starts with no display name, email change available, display
#        name change available ---
r = client.get("/auth/me", headers=H)
assert r.status_code == 200, (r.status_code, r.text)
me = r.json()
assert me["display_name"] is None and me["email_change_available"] is True, me
assert me["display_name_change_available"] is True and me["display_name_next_change_at"] is None, me
print("1. OK  fresh account: no display name, both changes available")

# --- B. set a display name (trimmed), cooldown now active ---
r = client.patch("/auth/me/display-name", json={"display_name": "  Founder Joe  "}, headers=H)
assert r.status_code == 200, (r.status_code, r.text)
body = r.json()
assert body["display_name"] == "Founder Joe", body  # trimmed
assert body["display_name_change_available"] is False and body["display_name_next_change_at"], body
print("2. OK  display name set (trimmed), cooldown now active")

# --- C. a second change immediately after is refused - once every 60 days ---
r = client.patch("/auth/me/display-name", json={"display_name": "Someone Else"}, headers=H)
assert r.status_code == 400 and "60 days" in r.json()["detail"], (r.status_code, r.text)
# unchanged - the refused attempt didn't overwrite the existing name
r = client.get("/auth/me", headers=H)
assert r.json()["display_name"] == "Founder Joe", r.json()
print("3. OK  second display-name change within 60 days refused, name unchanged")

# --- D. once the cooldown has genuinely elapsed, a change (including
#        clearing it to blank) is allowed again ---
db_user = db.query(User).filter_by(id=u.id).first()
db_user.display_name_changed_at = datetime.utcnow() - timedelta(days=61)
db.commit()
r = client.patch("/auth/me/display-name", json={"display_name": "   "}, headers=H)
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["display_name"] is None, r.json()  # blank clears it back to null
print("4. OK  after 60+ days, change allowed again - blank clears it back to null")

# --- E. wrong current password blocks both email and password change ---
r = client.patch("/auth/me/email", json={"new_email": "new@acme.example.com", "current_password": "wrongpass"}, headers=H)
assert r.status_code == 401, (r.status_code, r.text)
r = client.patch("/auth/me/password", json={"current_password": "wrongpass", "new_password": "newpassword1"}, headers=H)
assert r.status_code == 401, (r.status_code, r.text)
print("5. OK  wrong current password blocks email and password change")

# --- F. real email change works once ---
r = client.patch("/auth/me/email", json={"new_email": "NEW@Acme.example.com", "current_password": "supersecret1"}, headers=H)
assert r.status_code == 200, (r.status_code, r.text)
body = r.json()
assert body["email"] == "new@acme.example.com" and body["email_change_available"] is False, body  # normalized lowercase
print("6. OK  email changed once, normalized lowercase, email_change_available flips false")

# --- G. a second change is refused, even with the right password ---
r = client.patch("/auth/me/email", json={"new_email": "third@acme.example.com", "current_password": "supersecret1"}, headers=H)
assert r.status_code == 400 and "once" in r.json()["detail"].lower(), (r.status_code, r.text)
print("7. OK  second email change refused - one per lifetime")

# --- H. can't change email to one already in use ---
other_user = User(tenant_id=t.id, email="taken@acme.example.com", role="analyst", password_hash=hash_password("otherpass1"))
db.add(other_user); db.commit()
# founder already used their change (G above) - use a fresh account to test the collision check itself
u2 = User(tenant_id=t.id, email="second@acme.example.com", role="analyst", password_hash=hash_password("secondpass1"))
db.add(u2); db.commit()
H2 = {"Authorization": f"Bearer {create_access_token(u2.id, t.id, u2.role)}"}
r = client.patch("/auth/me/email", json={"new_email": "taken@acme.example.com", "current_password": "secondpass1"}, headers=H2)
assert r.status_code == 400 and "already exists" in r.json()["detail"], (r.status_code, r.text)
print("8. OK  can't change email to one another user already has")

# --- I. password change works, and the new password actually logs in ---
r = client.patch("/auth/me/password", json={"current_password": "secondpass1", "new_password": "brandnewpass1"}, headers=H2)
assert r.status_code == 200, (r.status_code, r.text)
r = client.post("/auth/login", json={"email": "second@acme.example.com", "password": "brandnewpass1"})
assert r.status_code == 200 and r.json().get("access_token"), (r.status_code, r.text)
r = client.post("/auth/login", json={"email": "second@acme.example.com", "password": "secondpass1"})
assert r.status_code == 401, "old password should no longer work"
print("9. OK  password change takes effect - new password logs in, old one doesn't")

print("\nALL CHECKS PASSED")
