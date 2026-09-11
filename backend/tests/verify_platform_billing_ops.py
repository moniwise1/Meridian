"""
Throwaway verification for the platform Tenants page's billing detail
(plan price, last transaction reference, Paystack customer code) and the
owner-only "deactivate + full refund" fraud/abuse override.
Real SQLite + FastAPI TestClient; only the Paystack HTTP calls are
stubbed. Run from backend/:
  PYTHONPATH=$(pwd) python tests/verify_platform_billing_ops.py
"""
import base64, os, tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake_secret"

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, PlatformStaff
from app.security.auth import hash_password
from app.security.platform_auth import create_platform_access_token
from app.billing import paystack
from app.billing.paystack import PaystackError

init_db()
client = TestClient(app)
db = SessionLocal()

owner = PlatformStaff(email="owner@meridian.example.com", password_hash=hash_password("ownerpass1"), role="owner")
support = PlatformStaff(email="support@meridian.example.com", password_hash=hash_password("supportpass1"), role="support")
db.add_all([owner, support]); db.commit()
OWNER_H = {"Authorization": f"Bearer {create_platform_access_token(owner.id, owner.role)}"}
SUPPORT_H = {"Authorization": f"Bearer {create_platform_access_token(support.id, support.role)}"}


def mk_active_tenant(name, plan="pro", with_subscription_handle=True):
    t = Tenant(
        name=name, subscription_status="active", plan=plan,
        paid_at=datetime.utcnow() - timedelta(days=10),
        subscription_expires_at=datetime.utcnow() + timedelta(days=20),
        last_transaction_reference=f"ref-{name}",
        paystack_customer_code=f"CUS_{name}",
    )
    if with_subscription_handle:
        t.paystack_subscription_code = f"SUB_{name}"
        t.paystack_email_token = f"tok-{name}"
    db.add(t); db.commit(); db.refresh(t)
    return t

# --- A. billing detail shows up on GET /platform/tenants ---
priced = mk_active_tenant("Priced Co")
r = client.get("/platform/tenants", headers=OWNER_H)
assert r.status_code == 200, (r.status_code, r.text)
row = next(x for x in r.json() if x["id"] == priced.id)
assert row["plan_amount_naira"] and "/mo" in row["plan_amount_naira"], row
assert row["last_transaction_reference"] == "ref-Priced Co", row
assert row["paystack_customer_code"] == "CUS_Priced Co", row
print(f"1. OK  tenant billing detail exposed: {row['plan_amount_naira']}, ref={row['last_transaction_reference']}")

# --- B. deactivate-and-refund needs owner, not support ---
t2 = mk_active_tenant("Support Blocked Co")
r = client.post(f"/platform/tenants/{t2.id}/deactivate-and-refund", json={"reason": "suspected card fraud"}, headers=SUPPORT_H)
assert r.status_code == 403, (r.status_code, r.text)
print("2. OK  support role can't deactivate-and-refund (owner-only)")

# --- C. reason is required (too short) ---
r = client.post(f"/platform/tenants/{t2.id}/deactivate-and-refund", json={"reason": "x"}, headers=OWNER_H)
assert r.status_code == 422, (r.status_code, r.text)
print("3. OK  a near-empty reason is rejected")

# --- D. refuses a tenant with no active subscription ---
inactive = Tenant(name="Inactive Co", subscription_status="cancelled")
db.add(inactive); db.commit()
r = client.post(f"/platform/tenants/{inactive.id}/deactivate-and-refund", json={"reason": "checking the guard"}, headers=OWNER_H)
assert r.status_code == 400, (r.status_code, r.text)
print("4. OK  refuses a tenant that isn't currently active")

# --- E. happy path: disable + refund both succeed ---
happy = mk_active_tenant("Fraud Suspect Co")
calls = {"disable": None, "refund": None}
paystack.disable_subscription = lambda code, token, client=None: calls.__setitem__("disable", (code, token)) or {}
paystack.refund_transaction = lambda ref, client=None: calls.__setitem__("refund", ref) or {}
r = client.post(f"/platform/tenants/{happy.id}/deactivate-and-refund",
                json={"reason": "customer used a stolen card, chargeback risk"}, headers=OWNER_H)
assert r.status_code == 200, (r.status_code, r.text)
body = r.json()
assert body["subscription_status"] == "refunded", body
assert body["plan"] is None and body["subscription_expires_at"] is None, body
assert calls["disable"] == ("SUB_Fraud Suspect Co", "tok-Fraud Suspect Co"), calls
assert calls["refund"] == "ref-Fraud Suspect Co", calls
print("5. OK  happy path: Paystack subscription disabled + refunded, tenant downgraded, status='refunded'")

# --- F. refund call fails -> still deactivated, but honestly 'cancelled' not 'refunded' ---
flaky = mk_active_tenant("Flaky Refund Co")
paystack.disable_subscription = lambda code, token, client=None: {}
def _boom(ref, client=None):
    raise PaystackError("Transaction already refunded")
paystack.refund_transaction = _boom
r = client.post(f"/platform/tenants/{flaky.id}/deactivate-and-refund",
                json={"reason": "trying again after a first attempt"}, headers=OWNER_H)
assert r.status_code == 200, (r.status_code, r.text)
body = r.json()
assert body["subscription_status"] == "cancelled", body  # NOT 'refunded' - it didn't actually happen
print("6. OK  refund API failure -> tenant still deactivated, but marked 'cancelled' not falsely 'refunded'")

# --- G. no Paystack subscription on file (e.g. a comped tenant) - deactivates cleanly, no Paystack calls needed ---
comped = mk_active_tenant("Comped Co", with_subscription_handle=False)
comped.last_transaction_reference = None
db.commit()
called = {"disable": False, "refund": False}
paystack.disable_subscription = lambda *a, **k: called.__setitem__("disable", True)
paystack.refund_transaction = lambda *a, **k: called.__setitem__("refund", True)
r = client.post(f"/platform/tenants/{comped.id}/deactivate-and-refund",
                json={"reason": "comped tenant being investigated"}, headers=OWNER_H)
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["subscription_status"] == "cancelled", r.json()
assert called == {"disable": False, "refund": False}, "should not call Paystack with nothing on file"
print("7. OK  a tenant with no real Paystack handle deactivates cleanly without calling Paystack")

print("\nALL CHECKS PASSED")
