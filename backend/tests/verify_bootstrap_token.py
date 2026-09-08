"""
Throwaway verification for security fix #2 - POST /platform/bootstrap must
require PLATFORM_BOOTSTRAP_TOKEN, not just "no staff exist yet".
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import PlatformStaff
from app.config import settings

init_db()
client = TestClient(app)
REG = {"email": "root@meridianhq.com", "password": "supersecret1"}

# --- 1. token unset (default) -> bootstrap disabled ---
settings.platform_bootstrap_token = ""
r = client.post("/platform/bootstrap", json={**REG, "bootstrap_token": "anything"})
assert r.status_code == 403 and "disabled" in r.json()["detail"].lower(), (r.status_code, r.text)
assert SessionLocal().query(PlatformStaff).count() == 0
print("1. OK  token unset -> 403 (bootstrap disabled), no account created")

# --- 2. token set, wrong token supplied -> 403 ---
settings.platform_bootstrap_token = "the-real-one-time-secret"
r = client.post("/platform/bootstrap", json={**REG, "bootstrap_token": "wrong"})
assert r.status_code == 403 and "invalid bootstrap token" in r.json()["detail"].lower(), (r.status_code, r.text)
r = client.post("/platform/bootstrap", json={**REG})  # missing entirely
assert r.status_code == 403, (r.status_code, r.text)
assert SessionLocal().query(PlatformStaff).count() == 0
print("2. OK  wrong / missing token -> 403, no account created")

# --- 3. token set + correct -> owner created ---
r = client.post("/platform/bootstrap", json={**REG, "bootstrap_token": "the-real-one-time-secret"})
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["role"] == "owner"
assert SessionLocal().query(PlatformStaff).count() == 1
print("3. OK  correct token -> first owner created")

# --- 4. once a staff account exists, bootstrap is closed even WITH the token ---
r = client.post("/platform/bootstrap",
                json={"email": "second@meridianhq.com", "password": "supersecret1",
                      "bootstrap_token": "the-real-one-time-secret"})
assert r.status_code == 403 and "already exists" in r.json()["detail"].lower(), (r.status_code, r.text)
assert SessionLocal().query(PlatformStaff).count() == 1
print("4. OK  staff already exists -> 403 even with the correct token")

print("\nALL CHECKS PASSED")
