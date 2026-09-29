"""
Verification for recording a payment that arrived outside the gateway.

The first customers are likely to pay by bank transfer against an
invoice, which means a staff member marks them active by hand. Until now
that always granted 30 days, so an annual customer would have been
locked out eleven months early - and the first anyone would have known
is the customer calling.

Real SQLite + FastAPI TestClient, no stubbing of the code under test.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_manual_activation.py
"""
import base64
import os
import tempfile
from datetime import datetime

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, PlatformStaff
from app.security.auth import hash_password
from app.security.platform_auth import create_platform_access_token
from app.billing.plans import period_days

init_db()
client = TestClient(app)
db = SessionLocal()

owner = PlatformStaff(email="owner@meridian.test", password_hash=hash_password("supersecret1"), role="owner")
db.add(owner)
db.commit()
OWNER = {"Authorization": f"Bearer {create_platform_access_token(owner.id, owner.role)}"}


def new_tenant(name: str) -> str:
    t = Tenant(name=name, subscription_status="none")
    db.add(t)
    db.commit()
    return t.id


def days_left(tenant_id: str) -> int:
    db.expire_all()
    t = db.query(Tenant).filter_by(id=tenant_id).one()
    return round((t.subscription_expires_at - datetime.utcnow()).total_seconds() / 86400)


# --- 1. an annual payment grants a year, not a month ----------------------
tid = new_tenant("Annual Payer Ltd")
r = client.patch(f"/platform/tenants/{tid}", headers=OWNER,
                 json={"subscription_status": "active", "plan": "pro", "billing_interval": "annual"})
assert r.status_code == 200, r.text
assert days_left(tid) == period_days("annual") == 365, days_left(tid)
db.expire_all()
t = db.query(Tenant).filter_by(id=tid).one()
assert (t.plan, t.billing_interval, t.subscription_status) == ("pro", "annual", "active")
assert t.paid_at is not None, "paid_at must be set so the refund window has an anchor"
print("1. OK  a bank transfer recorded as annual grants 365 days, not 30")


# --- 2. a monthly payment still grants a month ----------------------------
tid = new_tenant("Monthly Payer Ltd")
r = client.patch(f"/platform/tenants/{tid}", headers=OWNER,
                 json={"subscription_status": "active", "plan": "basic", "billing_interval": "monthly"})
assert r.status_code == 200, r.text
assert days_left(tid) == 30, days_left(tid)
print("2. OK  a monthly payment still grants 30 days")


# --- 3. no interval given behaves exactly as before ------------------------
# The old call shape must keep working: staff comping someone without
# thinking about intervals should not silently get a year.
tid = new_tenant("Comped Ltd")
r = client.patch(f"/platform/tenants/{tid}", headers=OWNER,
                 json={"subscription_status": "active", "plan": "premium"})
assert r.status_code == 200, r.text
assert days_left(tid) == 30, days_left(tid)
print("3. OK  omitting the interval still means monthly - the old behaviour is unchanged")


# --- 4. rubbish intervals are refused -------------------------------------
tid = new_tenant("Bad Interval Ltd")
r = client.patch(f"/platform/tenants/{tid}", headers=OWNER,
                 json={"subscription_status": "active", "billing_interval": "forever"})
assert r.status_code == 400, r.text
db.expire_all()
assert db.query(Tenant).filter_by(id=tid).one().subscription_status == "none", \
    "a refused request must not have activated the tenant"
print("4. OK  an unknown interval is refused and changes nothing")


# --- 5. deactivating clears the interval with everything else -------------
tid = new_tenant("Leaving Ltd")
client.patch(f"/platform/tenants/{tid}", headers=OWNER,
             json={"subscription_status": "active", "plan": "pro", "billing_interval": "annual"})
r = client.patch(f"/platform/tenants/{tid}", headers=OWNER, json={"subscription_status": "cancelled"})
assert r.status_code == 200, r.text
db.expire_all()
t = db.query(Tenant).filter_by(id=tid).one()
assert (t.subscription_expires_at, t.plan, t.billing_interval) == (None, None, None), \
    "a cancelled tenant must not keep a live expiry, plan or interval"
print("5. OK  cancelling clears the expiry, the plan and the interval together")


# --- 6. the refund window is not reopened by a later payment --------------
tid = new_tenant("Renewing Ltd")
client.patch(f"/platform/tenants/{tid}", headers=OWNER,
             json={"subscription_status": "active", "billing_interval": "monthly"})
db.expire_all()
first_paid_at = db.query(Tenant).filter_by(id=tid).one().paid_at
client.patch(f"/platform/tenants/{tid}", headers=OWNER, json={"subscription_status": "none"})
client.patch(f"/platform/tenants/{tid}", headers=OWNER,
             json={"subscription_status": "active", "billing_interval": "annual"})
db.expire_all()
assert db.query(Tenant).filter_by(id=tid).one().paid_at == first_paid_at, \
    "paid_at moved, which would reopen the refund window on every renewal"
print("6. OK  recording a later payment never reopens the refund window")


db.close()
print("\nALL MANUAL ACTIVATION CHECKS PASSED")
