"""
Verification for annual billing: that choosing "annual" actually checks out
against the annual Paystack plan at the annual price, and that an annual
payment buys a YEAR - not a 30-day period that quietly lapses eleven months
early. Real SQLite + FastAPI TestClient; only Paystack's HTTP calls are
stubbed, the same way verify_billing_binding.py does it.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_annual_billing.py
"""
import base64
import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake_secret"
os.environ["PAYSTACK_PLAN_CODE_BASIC"] = "PLN_basic"
os.environ["PAYSTACK_PLAN_CODE_PRO"] = "PLN_pro"
os.environ["PAYSTACK_PLAN_CODE_PREMIUM"] = "PLN_premium"
os.environ["PAYSTACK_PLAN_CODE_BASIC_ANNUAL"] = "PLN_basic_yr"
os.environ["PAYSTACK_PLAN_CODE_PRO_ANNUAL"] = "PLN_pro_yr"
# Premium's annual plan deliberately left UNCONFIGURED - check 6.

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User, Notification
from app.security.auth import hash_password, create_access_token
from app.billing import paystack
from app.agents import notifications
from app.billing.plans import PLANS, annual_amount_for, interval_for_paystack_code

init_db()
client = TestClient(app)
db = SessionLocal()


def mk_admin(name, email):
    t = Tenant(name=name, subscription_status="none")
    db.add(t)
    db.flush()
    u = User(tenant_id=t.id, email=email, role="admin", password_hash=hash_password("supersecret1"))
    db.add(u)
    db.commit()
    return t, {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


checkouts = []


def _fake_initialize(email, plan_code, amount, callback_url, metadata=None, client=None):
    checkouts.append({"plan_code": plan_code, "amount": amount, "metadata": metadata})
    return {"authorization_url": "https://checkout.paystack.test/x",
            "reference": f"ref-{len(checkouts)}", "access_code": "a"}


paystack.initialize_subscription_transaction = _fake_initialize

sent_emails = []
notifications._send_best_effort = lambda to, subject, body, *a, **k: sent_emails.append(
    {"to": to, "subject": subject, "body": body})

refunds = []
paystack.refund_transaction = lambda reference, client=None: refunds.append(reference) or {"status": True}
paystack.disable_subscription = lambda code, token, client=None: {"status": True}


def _signed_webhook(payload):
    body = json.dumps(payload).encode()
    sig = hmac.new(b"sk_test_fake_secret", body, hashlib.sha512).hexdigest()
    return client.post("/billing/webhook", content=body,
                       headers={"x-paystack-signature": sig, "content-type": "application/json"})


# --- 1. the annual price is exactly 12 months less 5% ----------------------
expected = {"basic": 8_550_000, "pro": 28_500_000, "premium": 85_500_000}
for key, plan in PLANS.items():
    assert plan.annual_amount == expected[key], (key, plan.annual_amount)
    assert plan.annual_amount == int(plan.amount * 12 * 0.95), key
print("1. OK  annual = 12 x monthly less 5%: NGN 85,500 / 285,000 / 855,000")


# --- 2. /billing/plans exposes both prices and what's checkout-ready -------
plans = {p["key"]: p for p in client.get("/billing/plans").json()}
assert plans["pro"]["amount"] == 2_500_000 and plans["pro"]["annual_amount"] == 28_500_000, plans["pro"]
assert plans["pro"]["annual_discount_percent"] == 5
assert plans["basic"]["annual_configured"] is True
assert plans["premium"]["configured"] is True and plans["premium"]["annual_configured"] is False
print("2. OK  /billing/plans returns monthly + annual price and per-interval availability")


# --- 3. subscribing annually checks out the ANNUAL plan at the ANNUAL price
tenant, H = mk_admin("Annual Co", "a@annualco.com")
r = client.post("/billing/subscribe", headers=H,
                json={"plan": "pro", "interval": "annual", "callback_url": "https://x/billing"})
assert r.status_code == 200, r.text
assert checkouts[-1]["plan_code"] == "PLN_pro_yr", checkouts[-1]
assert checkouts[-1]["amount"] == 28_500_000, checkouts[-1]
db.expire_all()
assert db.get(Tenant, tenant.id).billing_interval == "annual"
print("3. OK  interval=annual checks out PLN_pro_yr for NGN 285,000")


# --- 4. an annual payment buys a year, not 30 days --------------------------
r = _signed_webhook({"event": "charge.success", "data": {
    "reference": "ref-1", "customer": {"customer_code": "CUS_annual"},
    "plan": {"plan_code": "PLN_pro_yr"}, "metadata": {"tenant_id": tenant.id}}})
assert r.status_code == 200, r.text
db.expire_all()
t = db.get(Tenant, tenant.id)
assert t.subscription_status == "active" and t.plan == "pro", (t.subscription_status, t.plan)
days_left = (t.subscription_expires_at - datetime.utcnow()).days
assert 363 <= days_left <= 365, f"annual payment bought {days_left} days, not a year"
status = client.get("/billing/status", headers=H).json()
assert status["billing_interval"] == "annual", status
notice = db.query(Notification).filter_by(tenant_id=tenant.id, kind="subscription_activated").one()
assert "₦285,000/year" in notice.body, notice.body
assert "/month" not in notice.body, notice.body
email = next(e for e in sent_emails if e["to"] == "a@annualco.com")
assert "Amount: \u20a6285,000/year\n" in email["body"], email["body"]
assert "/year / month" not in email["body"] and "/month / month" not in email["body"], email["body"]
assert "within the first 30 days" in email["body"], email["body"]
print(f"4. OK  annual payment -> active for {days_left + 1} days; status, notice and email all say annual")


# --- 5. the verified plan code wins over what /subscribe recorded ----------
#        (optimistic-then-verified, the same as `plan`): the tenant picked
#        monthly, but Paystack says the annual plan was actually paid for.
tenant2, H2 = mk_admin("Switched Co", "a@switchedco.com")
client.post("/billing/subscribe", headers=H2,
            json={"plan": "basic", "interval": "monthly", "callback_url": "https://x/billing"})
db.expire_all()
assert db.get(Tenant, tenant2.id).billing_interval == "monthly"
_signed_webhook({"event": "charge.success", "data": {
    "reference": "ref-2", "customer": {"customer_code": "CUS_switched"},
    "plan": {"plan_code": "PLN_basic_yr"}, "metadata": {"tenant_id": tenant2.id}}})
db.expire_all()
t2 = db.get(Tenant, tenant2.id)
assert t2.billing_interval == "annual", t2.billing_interval
assert (t2.subscription_expires_at - datetime.utcnow()) > timedelta(days=300)
print("5. OK  what Paystack verified was paid for overrides the interval /subscribe recorded")


# --- 6. an annual plan that isn't configured is refused, never charged -----
tenant3, H3 = mk_admin("Premium Co", "a@premiumco.com")
before = len(checkouts)
r = client.post("/billing/subscribe", headers=H3,
                json={"plan": "premium", "interval": "annual", "callback_url": "https://x/billing"})
assert r.status_code == 500 and "annual" in r.json()["detail"], r.text
assert len(checkouts) == before, "a checkout was started for an unconfigured annual plan"
print("6. OK  unconfigured annual plan -> clear refusal, no checkout started")


# --- 7. monthly is unchanged, and still the default -----------------------
tenant4, H4 = mk_admin("Monthly Co", "a@monthlyco.com")
r = client.post("/billing/subscribe", headers=H4,
                json={"plan": "basic", "callback_url": "https://x/billing"})   # no interval at all
assert r.status_code == 200, r.text
assert checkouts[-1]["plan_code"] == "PLN_basic" and checkouts[-1]["amount"] == 750_000, checkouts[-1]
_signed_webhook({"event": "charge.success", "data": {
    "reference": checkouts and f"ref-{len(checkouts)}", "customer": {"customer_code": "CUS_monthly"},
    "plan": {"plan_code": "PLN_basic"}, "metadata": {"tenant_id": tenant4.id}}})
db.expire_all()
t4 = db.get(Tenant, tenant4.id)
assert t4.billing_interval == "monthly"
assert 29 <= (t4.subscription_expires_at - datetime.utcnow()).days <= 30
email = next(e for e in sent_emails if e["to"] == "a@monthlyco.com")
assert "Amount: \u20a67,500/month\n" in email["body"], email["body"]
assert "within the first 7 days" in email["body"], email["body"]
print("7. OK  no interval -> monthly plan, monthly price, 30-day period, 7-day refund in the email")


# --- 8. anything other than monthly/annual is rejected, not guessed --------
r = client.post("/billing/subscribe", headers=H4,
                json={"plan": "basic", "interval": "weekly", "callback_url": "https://x/billing"})
assert r.status_code == 422, (r.status_code, r.text)
print("8. OK  an unknown interval is a 422, never silently treated as monthly")


# --- 9. an unconfigured plan code can never be mistaken for a real one -----
assert interval_for_paystack_code("") is None and interval_for_paystack_code(None) is None
assert interval_for_paystack_code("PLN_nobody") is None
assert annual_amount_for(750_000) == 8_550_000
print("9. OK  empty/unknown plan codes resolve to nothing")

# --- 10. the refund window is 30 days on annual, 7 on monthly --------------
plans = {p["key"]: p for p in client.get("/billing/plans").json()}
assert plans["pro"]["refund_window_days"] == 7 and plans["pro"]["annual_refund_window_days"] == 30
status = client.get("/billing/status", headers=H).json()     # the annual tenant from check 3/4
t = db.get(Tenant, tenant.id)
until = datetime.fromisoformat(status["refund_eligible_until"])
assert abs((until - t.paid_at) - timedelta(days=30)) < timedelta(seconds=5), (until, t.paid_at)
print("10. OK  /billing/plans states both windows; an annual tenant's refund deadline is paid_at + 30 days")


def _cancel_after(label, email, interval, plan_code, days_since_paid):
    """A real /billing/cancel on a tenant whose first payment was N days ago."""
    tn, hdr = mk_admin(label, email)
    tn.subscription_status, tn.plan, tn.billing_interval = "active", "pro", interval
    tn.paid_at = datetime.utcnow() - timedelta(days=days_since_paid)
    tn.subscription_expires_at = datetime.utcnow() + timedelta(days=10)
    tn.paystack_plan_code = plan_code
    tn.paystack_subscription_code, tn.paystack_email_token = "SUB_x", "tok_x"
    tn.last_transaction_reference = f"ref-{label}"
    db.commit()
    before = len(refunds)
    r = client.post("/billing/cancel", headers=hdr)
    assert r.status_code == 200, r.text
    db.expire_all()
    return db.get(Tenant, tn.id).subscription_status, len(refunds) > before


# --- 11. day 20: an annual plan is refunded, a monthly one is not ----------
state, refunded = _cancel_after("Annual20", "a@annual20.com", "annual", "PLN_pro_yr", 20)
assert refunded and state == "refunded", (state, refunded)
state, refunded = _cancel_after("Monthly20", "a@monthly20.com", "monthly", "PLN_pro", 20)
assert not refunded and state == "cancelled", (state, refunded)
print("11. OK  cancelling on day 20: annual -> full refund, monthly -> cancelled, no refund")

# --- 12. day 31: past the annual window too ---------------------------------
state, refunded = _cancel_after("Annual31", "a@annual31.com", "annual", "PLN_pro_yr", 31)
assert not refunded and state == "cancelled", (state, refunded)
# and monthly still refunds inside its own 7 days
state, refunded = _cancel_after("Monthly5", "a@monthly5.com", "monthly", "PLN_pro", 5)
assert refunded and state == "refunded", (state, refunded)
print("12. OK  day 31 annual -> no refund; day 5 monthly -> refund (monthly window unchanged)")

db.close()
print("\nALL ANNUAL BILLING CHECKS PASSED")
