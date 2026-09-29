"""
Verification for paying by bank transfer.

Most Nigerian customers would rather transfer than type card details, so
checkout offers both. They are genuinely different products and the
difference is easy to get wrong:

  card     -> a real Paystack subscription that charges itself again
  transfer -> one period, paid once, that does NOT renew

Paystack's Pay with Transfer cannot make recurring payments, and its
Subscriptions API accepts card and direct debit only. Attaching a plan to
a transfer would create a subscription that can never take a second
payment - so the transfer path must send no plan at all, and the period
must come from what the customer chose rather than from Paystack.

Real SQLite + FastAPI TestClient. Only the HTTP calls to Paystack are
stubbed; the endpoint, the webhook, the signature check and the
activation are all the real code paths.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_transfer_payment.py
"""
import base64
import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake"
os.environ["PAYSTACK_PLAN_CODE_BASIC"] = "PLN_basic_monthly"
os.environ["PAYSTACK_PLAN_CODE_BASIC_ANNUAL"] = "PLN_basic_annual"

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User
from app.security.auth import hash_password, create_access_token
from app.billing import paystack
from app.billing.plans import period_days
from app.config import settings

init_db()
client = TestClient(app)
db = SessionLocal()

# Captures what the app asked Paystack for, without any network call.
sent: list[dict] = []


def fake_request(method, path, client=None, **kwargs):
    body = kwargs.get("json") or {}
    sent.append({"path": path, **body})
    return {"authorization_url": "https://checkout.paystack.test/x",
            "access_code": "ac_test", "reference": f"ref-{len(sent)}"}


paystack._request = fake_request


def new_tenant(name: str) -> tuple[str, dict]:
    t = Tenant(name=name, subscription_status="none")
    db.add(t)
    db.commit()
    u = User(tenant_id=t.id, email=f"{t.id[:8]}@example.com",
             password_hash=hash_password("supersecret1"), role="admin")
    db.add(u)
    db.commit()
    return t.id, {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def subscribe(headers, plan="basic", interval="monthly", method=None):
    payload = {"plan": plan, "callback_url": "https://app.test/billing/callback",
               "interval": interval}
    if method is not None:
        payload["method"] = method
    return client.post("/billing/subscribe", headers=headers, json=payload)


def deliver_webhook(tenant_id: str, reference: str, interval: str, method: str):
    """A real signed charge.success, exactly as Paystack would send it for
    a transfer: no `plan` object anywhere in the payload."""
    body = json.dumps({
        "event": "charge.success",
        "data": {
            "reference": reference,
            "channel": "bank_transfer",
            "customer": {"customer_code": f"CUS_{tenant_id[:6]}"},
            "metadata": {"tenant_id": tenant_id, "interval": interval, "method": method},
        },
    }).encode()
    sig = hmac.new(settings.paystack_secret_key.encode(), body, hashlib.sha512).hexdigest()
    return client.post("/billing/webhook", content=body,
                       headers={"x-paystack-signature": sig, "Content-Type": "application/json"})


def days_left(tenant_id: str) -> int:
    db.expire_all()
    t = db.query(Tenant).filter_by(id=tenant_id).one()
    return round((t.subscription_expires_at - datetime.utcnow()).total_seconds() / 86400)


# --- 1. a transfer checkout sends NO plan, and pins the channel ------------
sent.clear()
tid, hdrs = new_tenant("Transfer Co")
r = subscribe(hdrs, interval="monthly", method="transfer")
assert r.status_code == 200, r.text
call = sent[-1]
assert "plan" not in call, f"a plan was attached to a transfer: {call}"
assert call["channels"] == ["bank_transfer"], call
assert call["amount"] == settings.paystack_plan_amount_basic, call
assert call["metadata"]["method"] == "transfer", call
print("1. OK  a transfer checkout carries no plan and opens straight on bank transfer")


# --- 2. a card checkout is unchanged --------------------------------------
sent.clear()
tid_card, hdrs_card = new_tenant("Card Co")
r = subscribe(hdrs_card, interval="monthly", method="card")
assert r.status_code == 200, r.text
call = sent[-1]
assert call["plan"] == "PLN_basic_monthly", call
assert "channels" not in call, "the card path must not restrict channels"
print("2. OK  the card path still attaches its plan and restricts nothing")


# --- 3. omitting the method still means card ------------------------------
# Every client written before transfer existed must behave as it did.
sent.clear()
tid_old, hdrs_old = new_tenant("Old Client Co")
r = subscribe(hdrs_old)
assert r.status_code == 200, r.text
assert sent[-1]["plan"] == "PLN_basic_monthly", sent[-1]
print("3. OK  a request with no method is treated as card, as before")


# --- 4. a transfer payment activates for the period actually chosen -------
db.expire_all()
reference = db.query(Tenant).filter_by(id=tid).one().last_transaction_reference
r = deliver_webhook(tid, reference, "monthly", "transfer")
assert r.status_code == 200, r.text
db.expire_all()
t = db.query(Tenant).filter_by(id=tid).one()
assert t.subscription_status == "active", t.subscription_status
assert t.plan == "basic" and t.billing_interval == "monthly"
assert days_left(tid) == period_days("monthly") == 30, days_left(tid)
print("4. OK  a transfer with no plan in the payload still activates, for 30 days")


# --- 5. an annual transfer buys a year, not a month -----------------------
# The period has to come from what the customer chose, because Paystack
# sends back no plan to read it off.
sent.clear()
tid_y, hdrs_y = new_tenant("Annual Transfer Co")
r = subscribe(hdrs_y, interval="annual", method="transfer")
assert r.status_code == 200, r.text
assert "plan" not in sent[-1], sent[-1]
assert sent[-1]["amount"] == settings.paystack_plan_amount_basic * 12 * 95 // 100, sent[-1]
db.expire_all()
ref_y = db.query(Tenant).filter_by(id=tid_y).one().last_transaction_reference
assert deliver_webhook(tid_y, ref_y, "annual", "transfer").status_code == 200
assert days_left(tid_y) == period_days("annual") == 365, days_left(tid_y)
print("5. OK  an annual transfer buys 365 days at the discounted annual price")


# --- 6. a transfer leaves behind no subscription to cancel ----------------
# Someone who paid by card, lapsed, then paid by transfer would otherwise
# keep a dead subscription code, and /cancel would act on the wrong thing.
db.expire_all()
t = db.query(Tenant).filter_by(id=tid).one()
t.paystack_subscription_code = "SUB_stale"
t.paystack_email_token = "tok_stale"
t.subscription_status = "none"
db.commit()
r = subscribe(hdrs, interval="monthly", method="transfer")
assert r.status_code == 200, r.text
db.expire_all()
t = db.query(Tenant).filter_by(id=tid).one()
assert t.paystack_subscription_code is None and t.paystack_email_token is None, \
    "a stale subscription code survived a transfer checkout"
print("6. OK  a transfer clears any leftover subscription code from an earlier card")


# --- 7. an unsigned webhook is still refused ------------------------------
r = client.post("/billing/webhook", content=b'{"event":"charge.success","data":{}}',
                headers={"x-paystack-signature": "nonsense", "Content-Type": "application/json"})
assert r.status_code == 401, r.text
print("7. OK  the signature check still refuses a forged webhook")


# --- 8. a rubbish method is refused ---------------------------------------
tid_b, hdrs_b = new_tenant("Bad Method Co")
r = subscribe(hdrs_b, method="cheque")
assert r.status_code == 422, r.text
db.expire_all()
assert db.query(Tenant).filter_by(id=tid_b).one().subscription_status == "none"
print("8. OK  an unknown payment method is refused and starts no checkout")


db.close()
print("\nALL TRANSFER PAYMENT CHECKS PASSED")
