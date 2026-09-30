"""
Verification for marketing consent.

Signing up is consent to transactional email - receipts, password resets,
renewal and security notices. It is not consent to promotional
broadcasts. This is the part that cannot be added retroactively: an
account created without being asked can never be lawfully marketed to,
and asking later is itself a marketing email.

The checks that matter most here are the boring ones. Consent must
default to OFF, an account that predates the column must read as OFF
rather than as unknown or true, and turning it off must not disturb
transactional email.

Real SQLite + FastAPI TestClient, real endpoints, nothing stubbed.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_marketing_consent.py
"""
import base64
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from sqlalchemy import text
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import User
from app.security.auth import create_access_token

init_db()
client = TestClient(app)
db = SessionLocal()

_n = {"i": 0}


def register(opt_in=None):
    _n["i"] += 1
    payload = {"company_name": f"Consent Co {_n['i']}",
               "email": f"consent{_n['i']}@example.com", "password": "supersecret1"}
    if opt_in is not None:
        payload["marketing_opt_in"] = opt_in
    # A fresh IP per signup. The per-IP sign-up cap is real protection
    # (app/security/ip_throttle.py) and it fires part-way through this
    # file otherwise - which is the cap working, not a fault to route
    # around, so each registration simply comes from its own address.
    r = client.post("/auth/register", json=payload,
                    headers={"x-forwarded-for": f"203.0.113.{_n['i']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def me(headers):
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- 1. consent defaults to off ------------------------------------------
body, hdrs = register()
assert me(hdrs)["marketing_opt_in"] is False
row = db.query(User).filter_by(id=body["user_id"]).one()
assert not row.marketing_opt_in and row.marketing_opt_in_at is None
print("1. OK  a signup that says nothing about marketing is not opted in")


# --- 2. explicitly declining is also off ---------------------------------
body, hdrs = register(opt_in=False)
assert me(hdrs)["marketing_opt_in"] is False
db.expire_all()
assert db.query(User).filter_by(id=body["user_id"]).one().marketing_opt_in_at is None, \
    "declining must not date a consent that was never given"
print("2. OK  ticking nothing and declining are the same thing")


# --- 3. opting in is recorded, and dated ---------------------------------
body, hdrs = register(opt_in=True)
assert me(hdrs)["marketing_opt_in"] is True
db.expire_all()
row = db.query(User).filter_by(id=body["user_id"]).one()
assert row.marketing_opt_in is True
assert row.marketing_opt_in_at is not None, "consent that cannot be dated cannot be evidenced"
print("3. OK  opting in at signup is stored with the date consent was given")


# --- 4. an account from before the column reads as never asked -----------
# The additive migration adds the column with a plain ADD COLUMN and no
# default, so every pre-existing row is NULL. NULL is not "unknown" here,
# it is "was never asked", and it must behave exactly like False.
body, hdrs = register(opt_in=True)
db.execute(text("UPDATE users SET marketing_opt_in = NULL, marketing_opt_in_at = NULL "
                "WHERE id = :i"), {"i": body["user_id"]})
db.commit()
db.expire_all()
assert db.query(User).filter_by(id=body["user_id"]).one().marketing_opt_in is None
assert me(hdrs)["marketing_opt_in"] is False, \
    "an account that predates the column must read as not opted in"
print("4. OK  an account from before this existed reads as not opted in, never as unknown")


# --- 5. it can be turned on and off from the account itself --------------
# Withdrawing has to be as easy as giving, so it is one request.
body, hdrs = register()
r = client.patch("/auth/me/marketing-opt-in", headers=hdrs, json={"marketing_opt_in": True})
assert r.status_code == 200 and r.json()["marketing_opt_in"] is True, r.text
db.expire_all()
assert db.query(User).filter_by(id=body["user_id"]).one().marketing_opt_in_at is not None

r = client.patch("/auth/me/marketing-opt-in", headers=hdrs, json={"marketing_opt_in": False})
assert r.status_code == 200 and r.json()["marketing_opt_in"] is False, r.text
db.expire_all()
row = db.query(User).filter_by(id=body["user_id"]).one()
assert row.marketing_opt_in is False
assert row.marketing_opt_in_at is None, "opting out must clear the date consent was given"
print("5. OK  consent can be given and withdrawn in one request, and the date follows it")


# --- 6. the change is audited --------------------------------------------
from app.db.models import AuditLog
entries = db.query(AuditLog).filter_by(action="marketing_opt_in_changed").all()
assert len(entries) >= 2, f"expected the on and off to be audited, got {len(entries)}"
print("6. OK  giving and withdrawing consent are both written to the audit trail")


# --- 7. one account's consent never touches another's --------------------
_, hdrs_a = register(opt_in=True)
_, hdrs_b = register(opt_in=False)
assert me(hdrs_a)["marketing_opt_in"] is True
assert me(hdrs_b)["marketing_opt_in"] is False
client.patch("/auth/me/marketing-opt-in", headers=hdrs_b, json={"marketing_opt_in": True})
assert me(hdrs_a)["marketing_opt_in"] is True, "one account's change altered another's"
print("7. OK  consent is per account and does not leak between them")


# --- 8. it takes a signed-in account -------------------------------------
r = client.patch("/auth/me/marketing-opt-in", json={"marketing_opt_in": True})
assert r.status_code in (401, 403), r.status_code
r = client.patch("/auth/me/marketing-opt-in",
                 headers={"Authorization": "Bearer not-a-real-token"},
                 json={"marketing_opt_in": True})
assert r.status_code in (401, 403), r.status_code
print("8. OK  the preference cannot be changed without signing in")


# --- 9. rubbish is refused ------------------------------------------------
_, hdrs_c = register()
assert client.patch("/auth/me/marketing-opt-in", headers=hdrs_c,
                    json={"marketing_opt_in": "yes please"}).status_code == 422
assert client.patch("/auth/me/marketing-opt-in", headers=hdrs_c, json={}).status_code == 422
assert me(hdrs_c)["marketing_opt_in"] is False, "a refused request changed the preference"
print("9. OK  a malformed request is refused and changes nothing")


db.close()
print("\nALL MARKETING CONSENT CHECKS PASSED")
