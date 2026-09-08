"""
Throwaway verification for the auth "lows": #26 (PBKDF2 600k + versioned
hash format + rehash-on-login), #27 (login timing equaliser), #20 (email
case-insensitivity). Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, hashlib, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import User
from app.security import auth
from app.security.auth import (
    hash_password, verify_password, password_needs_rehash, dummy_password_hash, PBKDF2_ITERATIONS,
)

# --- 1. new hash format ---
h = hash_password("hunter2hunter2")
assert h.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$") and h.count("$") == 3, h
assert verify_password("hunter2hunter2", h) and not verify_password("wrong", h)
assert PBKDF2_ITERATIONS == 600_000
print("1. OK  new hashes are pbkdf2_sha256$600000$salt$dk and verify correctly")

# --- 2. legacy 2-part hash still verifies ---
salt = os.urandom(16)
legacy_dk = hashlib.pbkdf2_hmac("sha256", b"oldpassword1", salt, 260_000)
legacy = f"{salt.hex()}${legacy_dk.hex()}"
assert verify_password("oldpassword1", legacy) and not verify_password("nope", legacy)
print("2. OK  legacy {salt}$dk hashes (260k) still verify")

# --- 3. password_needs_rehash ---
assert password_needs_rehash(legacy) is True
assert password_needs_rehash(f"pbkdf2_sha256$260000${salt.hex()}${legacy_dk.hex()}") is True
assert password_needs_rehash(h) is False
print("3. OK  password_needs_rehash: legacy & low-iteration -> True, current -> False")

# --- 4. dummy hash is a real verifiable hash (timing equaliser) ---
d = dummy_password_hash()
assert d.startswith("pbkdf2_sha256$") and verify_password("meridian-login-timing-equalizer", d)
assert dummy_password_hash() is d  # cached
print("4. OK  dummy_password_hash() is a real cached hash used to equalise the miss path")

# --- 5-8. end to end ---
init_db()
client = TestClient(app)
db = SessionLocal()

# 5. register mixed-case, log in lower-case
r = client.post("/auth/register", json={"company_name": "Acme", "email": "Bob@Acme.com", "password": "supersecret1"})
assert r.status_code == 200, r.text
stored_email = db.query(User).filter(User.email.ilike("%acme.com")).one().email
assert stored_email == "bob@acme.com", f"email stored un-normalized: {stored_email!r}"
r = client.post("/auth/login", json={"email": "  BOB@ACME.COM  ", "password": "supersecret1"})
assert r.status_code == 200 and r.json().get("access_token"), r.text
print("5. OK  registered 'Bob@Acme.com' stored lower-cased; login as '  BOB@ACME.COM  ' works")

# 6. duplicate registration in a different case -> 400
r = client.post("/auth/register", json={"company_name": "Acme2", "email": "bob@acme.com", "password": "supersecret1"})
assert r.status_code == 400 and "already exists" in r.json()["detail"], (r.status_code, r.text)
print("6. OK  re-registering the same address in another case -> 400")

# 7. a legacy-format hash gets upgraded on a successful login
u = db.query(User).filter_by(email="bob@acme.com").one()
u.password_hash = f"{salt.hex()}${hashlib.pbkdf2_hmac('sha256', b'supersecret1', salt, 260_000).hex()}"
db.commit()
assert password_needs_rehash(db.query(User).filter_by(email='bob@acme.com').one().password_hash)
r = client.post("/auth/login", json={"email": "bob@acme.com", "password": "supersecret1"})
assert r.status_code == 200, r.text
db.expire_all()
upgraded = db.query(User).filter_by(email="bob@acme.com").one().password_hash
assert upgraded.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$") and verify_password("supersecret1", upgraded)
print("7. OK  a legacy-format hash is transparently upgraded to 600k on successful login")

# 8. a legacy mixed-case row (predating normalization) still resolves
db.add(User(tenant_id="t", email="LEGACY@Corp.com", role="analyst", password_hash=hash_password("legacypw12")))
db.commit()
r = client.post("/auth/login", json={"email": "legacy@corp.com", "password": "legacypw12"})
assert r.status_code in (200, 403), r.status_code   # 403 possible only via subdomain check; never 401
assert r.status_code != 401, "case-insensitive lookup failed for a legacy mixed-case row"
print("8. OK  a legacy mixed-case stored email still resolves on lower-case login")

# 9. unknown email still just 401 (miss path runs verify_password against the dummy)
r = client.post("/auth/login", json={"email": "nobody@nowhere-x.com", "password": "whatever12"})
assert r.status_code == 401, (r.status_code, r.text)
print("9. OK  unknown email -> 401 (miss path exercised without error)")

print("\nALL CHECKS PASSED")
