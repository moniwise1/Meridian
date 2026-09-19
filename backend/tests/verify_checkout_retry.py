"""
Verification for retrying an unfinished checkout.

A tenant that opened Paystack's payment page and closed it without paying
used to be stuck in "pending" for good - the Billing page hid the plans and
there was no way to try again. /billing/subscribe now checks with Paystack
what happened to that earlier attempt first, so a retry is possible without
ever risking a second charge for someone who DID pay.

Real SQLite + FastAPI TestClient; only Paystack's HTTP calls are stubbed.
Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_checkout_retry.py
"""
import base64
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake_secret"
os.environ["PAYSTACK_PLAN_CODE_BASIC"] = "PLN_basic"
os.environ["PAYSTACK_PLAN_CODE_PRO"] = "PLN_pro"
os.environ["PAYSTACK_PLAN_CODE_PREMIUM"] = "PLN_premium"
os.environ["PAYSTACK_PLAN_CODE_PRO_ANNUAL"] = "PLN_pro_yr"

import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User
from app.security.auth import hash_password, create_access_token
from app.billing import paystack
from app.billing.paystack import PaystackError
from app.agents import notifications

init_db()
client = TestClient(app)
db = SessionLocal()
notifications._send_best_effort = lambda *a, **k: None

checkouts = []


def _fake_initialize(email, plan_code, amount, callback_url, metadata=None, client=None):
    checkouts.append({"plan_code": plan_code, "amount": amount})
    return {"authorization_url": "https://checkout.paystack.test/x",
            "reference": f"ref-new-{len(checkouts)}", "access_code": "a"}


paystack.initialize_subscription_transaction = _fake_initialize

# What Paystack says about each earlier reference. A value that is an
# Exception is raised instead of returned.
paystack_says = {}
verify_calls = []


def _fake_verify(reference, client=None):
    verify_calls.append(reference)
    answer = paystack_says[reference]
    if isinstance(answer, Exception):
        raise answer
    return answer


paystack.verify_transaction = _fake_verify

_n = [0]


def pending_tenant(previous_status_or_error, plan="basic", interval="monthly"):
    """A tenant stuck in "pending" from an earlier checkout, and what
    Paystack will say happened to that checkout."""
    _n[0] += 1
    ref = f"ref-old-{_n[0]}"
    t = Tenant(name=f"Pending {_n[0]}", subscription_status="pending", plan=plan,
               billing_interval=interval, last_transaction_reference=ref)
    db.add(t)
    db.flush()
    u = User(tenant_id=t.id, email=f"a@pending{_n[0]}.com", role="admin",
             password_hash=hash_password("supersecret1"))
    db.add(u)
    db.commit()
    if isinstance(previous_status_or_error, Exception):
        paystack_says[ref] = previous_status_or_error
    else:
        paystack_says[ref] = {"status": previous_status_or_error, "reference": ref,
                              "customer": {"customer_code": f"CUS_{_n[0]}"},
                              "plan": {"plan_code": "PLN_pro_yr"},
                              "metadata": {"tenant_id": t.id}}
    return t, ref, {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def subscribe(headers, plan="pro", interval="monthly"):
    before = len(checkouts)
    r = client.post("/billing/subscribe", headers=headers,
                    json={"plan": plan, "interval": interval, "callback_url": "https://x/billing"})
    return r, len(checkouts) > before


# --- 1. closed the payment page without paying -> can start again ---------
t, old_ref, H = pending_tenant("abandoned")
r, started = subscribe(H)
assert r.status_code == 200 and started, (r.status_code, r.text)
db.expire_all()
t = db.get(Tenant, t.id)
assert t.subscription_status == "pending" and t.last_transaction_reference == r.json()["reference"]
assert t.last_transaction_reference != old_ref
print("1. OK  abandoned earlier checkout -> a fresh checkout starts (no longer stuck)")

# --- 2. a failed earlier payment -> can start again -----------------------
t, _, H = pending_tenant("failed")
r, started = subscribe(H)
assert r.status_code == 200 and started, r.text
print("2. OK  failed earlier payment -> a fresh checkout starts")

# --- 3. THEY ACTUALLY PAID -> activated, NOT charged again ----------------
t, old_ref, H = pending_tenant("success", plan="pro", interval="annual")
r, started = subscribe(H, plan="basic")
assert r.status_code == 409, (r.status_code, r.text)
assert not started, "a second checkout was started for a tenant who had already paid"
assert "went through" in r.json()["detail"] and "haven't been charged again" in r.json()["detail"]
db.expire_all()
t = db.get(Tenant, t.id)
assert t.subscription_status == "active", t.subscription_status
assert t.plan == "pro" and t.billing_interval == "annual", (t.plan, t.billing_interval)
assert (t.subscription_expires_at - t.paid_at).days >= 364, "the earlier annual payment should buy a year"
print("3. OK  earlier payment succeeded -> activated on what was PAID for, no second checkout")

# --- 4. still being processed -> wait, don't start another -----------------
for in_flight in ("ongoing", "pending", "processing", "queued", "some_new_status"):
    t, old_ref, H = pending_tenant(in_flight)
    r, started = subscribe(H)
    assert r.status_code == 409 and not started, (in_flight, r.status_code, r.text)
    assert "still being processed" in r.json()["detail"], r.text
    db.expire_all()
    t = db.get(Tenant, t.id)
    assert t.subscription_status == "pending" and t.last_transaction_reference == old_ref
print("4. OK  payment still in progress (or an unknown status) -> asked to wait, nothing started")

# --- 5. Paystack has no record of it -> nothing can be charged, so retry ---
t, _, H = pending_tenant(PaystackError("Transaction reference not found"))
r, started = subscribe(H)
assert r.status_code == 200 and started, r.text
print("5. OK  Paystack has no record of the earlier attempt -> a fresh checkout starts")

# --- 6. Paystack can't be reached -> fail safe, never guess ---------------
t, old_ref, H = pending_tenant(httpx.ConnectError("network down"))
r, started = subscribe(H)
assert r.status_code == 502 and not started, (r.status_code, r.text)
t2, old_ref2, H2 = pending_tenant(PaystackError("Internal server error"))
r2, started2 = subscribe(H2)
assert r2.status_code == 502 and not started2, (r2.status_code, r2.text)
print("6. OK  Paystack unreachable or erroring -> stops safely (502), no new checkout")

# --- 7. an earlier payment for SOMEONE ELSE is never used -----------------
t, old_ref, H = pending_tenant("success")
paystack_says[old_ref]["metadata"] = {"tenant_id": "a-different-tenant"}
r, started = subscribe(H)
assert r.status_code == 403 and not started, (r.status_code, r.text)
db.expire_all()
assert db.get(Tenant, t.id).subscription_status == "pending"
print("7. OK  earlier 'successful' payment belonging to another tenant -> refused, not activated")

# --- 8. a first-time subscriber is unaffected (no Paystack re-check) ------
fresh = Tenant(name="Fresh", subscription_status="none")
db.add(fresh)
db.flush()
fu = User(tenant_id=fresh.id, email="a@fresh.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(fu)
db.commit()
FH = {"Authorization": f"Bearer {create_access_token(fu.id, fresh.id, fu.role)}"}
calls_before = len(verify_calls)
r, started = subscribe(FH)
assert r.status_code == 200 and started and len(verify_calls) == calls_before, \
    "a brand-new tenant should not trigger any Paystack re-check"
print("8. OK  a first-time subscriber never triggers a re-check")

db.close()
print("\nALL CHECKOUT RETRY CHECKS PASSED")
