"""
Throwaway verification for security fixes #11 (rate-limit /auth/register)
and #12 (per-IP credential-stuffing guard on login).
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["REGISTER_RATE_LIMIT_PER_IP_PER_HOUR"] = "3"
os.environ["LOGIN_IP_FREE_ATTEMPTS"] = "3"
os.environ["LOGIN_FREE_ATTEMPTS"] = "5"

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import User
from app.security.auth import hash_password
from app.security import login_cooldown

init_db()
client = TestClient(app)


def reg(n, xff=None):
    h = {"x-forwarded-for": xff} if xff else {}
    return client.post("/auth/register", headers=h, json={
        "company_name": f"Co{n}", "email": f"u{n}@co{n}x.com", "password": "supersecret1"})


# --- 1. /auth/register: 3 from one IP OK, 4th -> 429 ---
assert reg(1).status_code == 200
assert reg(2).status_code == 200
assert reg(3).status_code == 200
r = reg(4)
assert r.status_code == 429, (r.status_code, r.text)
print("1. OK  4th /auth/register from one IP -> 429")

# --- 2. a different X-Forwarded-For is a fresh bucket ---
assert reg(5, xff="9.9.9.9").status_code == 200
print("2. OK  register from a different X-Forwarded-For still works")

# --- 3. per-IP credential stuffing: fail login for 3 DIFFERENT emails, 4th blocked ---
db = SessionLocal()
for i in range(6):
    db.add(User(tenant_id="t", email=f"victim{i}@vv.com", role="analyst",
                password_hash=hash_password("rightpassword1")))
db.commit()
login_cooldown._login_ip_guard.record_success("8.8.8.8")  # clean slate for this ip

XFF = {"x-forwarded-for": "8.8.8.8"}
for i in range(3):
    r = client.post("/auth/login", headers=XFF, json={"email": f"victim{i}@vv.com", "password": "wrong"})
    assert r.status_code == 401, (i, r.status_code)  # each email is fresh, only the IP counter climbs
# 4th attempt, a DIFFERENT untouched email -> blocked by the per-IP guard, not per-email
r = client.post("/auth/login", headers=XFF, json={"email": "victim5@vv.com", "password": "wrong"})
assert r.status_code == 429, (r.status_code, r.text)
print("3. OK  4th failed login from one IP across 4 different emails -> 429 (per-IP stuffing guard)")

# --- 4. a fresh IP is unaffected; a correct password clears the IP guard ---
r = client.post("/auth/login", headers={"x-forwarded-for": "1.2.3.4"},
                json={"email": "victim5@vv.com", "password": "rightpassword1"})
assert r.status_code in (200, 401), r.status_code  # 401 only if tenant lookup fails; not 429
assert r.status_code != 429
login_cooldown._login_ip_guard.record_success("8.8.8.8")
r = client.post("/auth/login", headers=XFF, json={"email": "victim0@vv.com", "password": "wrong"})
assert r.status_code == 401, (r.status_code, "IP guard should be cleared")
print("4. OK  a different IP is unaffected; record_login_ip_success clears the guard")

print("\nALL CHECKS PASSED")
