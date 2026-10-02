"""
Verification for individual (one-person) accounts.

Meridian now sells to two kinds of customer: a business, which gets a
shared workspace at its own subdomain and teammates it invites, and an
individual, which is one person on a cheaper plan with no team and no
subdomain of its own.

The checks that matter are the boundaries between them. An individual
must not end up on a team plan - every individual plan is one seat, so
seats it could never fill would be sold to it - and a business must not
end up on a plan capped at one person. Neither must happen by picking the
other catalogue at checkout, by a platform staffer comping the wrong
plan, or by the subdomain backfill quietly handing an individual a web
address on the next boot. And every account that existed before any of
this must still read and behave exactly as a business.

Real SQLite + FastAPI TestClient, real endpoints, nothing stubbed except
the Paystack HTTP call itself.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_individual_accounts.py
"""
import base64
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake"
os.environ["PAYSTACK_PLAN_CODE_BASIC"] = "PLN_basic_monthly"
os.environ["PAYSTACK_PLAN_CODE_INDIVIDUAL_BASIC"] = "PLN_ind_basic_monthly"
os.environ["PAYSTACK_PLAN_CODE_INDIVIDUAL_BASIC_ANNUAL"] = "PLN_ind_basic_annual"

from sqlalchemy import text
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db, _backfill_tenant_subdomains
from app.db.models import Tenant
from app.billing import paystack
from app.billing.plans import (
    PLANS, BUSINESS_PLAN_KEYS, INDIVIDUAL_PLAN_KEYS, plans_for_account_type,
    account_type_for_plan, normalize_account_type, seat_limit_for, annual_amount_for,
)

init_db()
client = TestClient(app)
db = SessionLocal()

sent: list[dict] = []


def fake_request(method, path, client=None, **kwargs):
    body = kwargs.get("json") or {}
    sent.append({"path": path, **body})
    return {"authorization_url": "https://checkout.paystack.test/x",
            "access_code": "ac_test", "reference": f"ref-{len(sent)}"}


paystack._request = fake_request

_n = {"i": 0}


def register(account_type=None, name=None):
    _n["i"] += 1
    payload = {"company_name": name or f"Signup {_n['i']}",
               "email": f"signup{_n['i']}@example.com", "password": "supersecret1"}
    if account_type is not None:
        payload["account_type"] = account_type
    # A fresh IP per signup: the per-IP sign-up cap is real protection
    # (app/security/ip_throttle.py) and fires part-way through this file
    # otherwise, which is the cap working rather than a fault to route
    # around.
    r = client.post("/auth/register", json=payload,
                    headers={"x-forwarded-for": f"198.51.100.{_n['i']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


# --- 1. the two catalogues are disjoint and complete ---------------------
# Every plan belongs to exactly one catalogue. A plan in neither would be
# unsellable to anyone; a plan in both would defeat the whole boundary.
assert set(BUSINESS_PLAN_KEYS).isdisjoint(INDIVIDUAL_PLAN_KEYS)
assert set(BUSINESS_PLAN_KEYS) | set(INDIVIDUAL_PLAN_KEYS) == set(PLANS), \
    "every plan must belong to exactly one catalogue"
for key in INDIVIDUAL_PLAN_KEYS:
    assert account_type_for_plan(key) == "individual"
    assert seat_limit_for(key) == 1, f"{key} is an individual plan and must be one seat"
for key in BUSINESS_PLAN_KEYS:
    assert account_type_for_plan(key) == "business"
print("1. OK  every plan belongs to exactly one catalogue, and individual plans are one seat")


# --- 2. the prices are the ones that were agreed -------------------------
# Hardcoded on purpose. These are what the site advertises and what
# Paystack is configured to charge; a typo in a plan amount is a billing
# incident, not a cosmetic bug, so it gets asserted literally rather than
# recomputed from the same settings the code under test reads.
expected = {"individual_basic": 350_000, "individual_pro": 750_000,
            "individual_premium": 1_500_000}
for key, monthly in expected.items():
    plan = PLANS[key]
    assert plan.amount == monthly, f"{key} is {plan.amount}, expected {monthly}"
    assert plan.annual_amount == annual_amount_for(monthly), \
        f"{key} annual price does not match the standard discount"
assert PLANS["individual_basic"].annual_amount == 3_990_000   # NGN 39,900
assert PLANS["individual_pro"].annual_amount == 8_550_000     # NGN 85,500
assert PLANS["individual_premium"].annual_amount == 17_100_000  # NGN 171,000
print("2. OK  individual prices are 3,500 / 7,500 / 15,000 a month, 5% off for a year")


# --- 3. the caps are the ones that were agreed ---------------------------
for key, queries in (("individual_basic", 35), ("individual_pro", 75),
                     ("individual_premium", 150)):
    plan = PLANS[key]
    assert plan.query_limit == queries, f"{key} allows {plan.query_limit} questions"
    assert plan.document_limit == queries, \
        f"{key} must allow as many downloads as questions ({queries})"
print("3. OK  individual plans allow 35 / 75 / 150 questions and the same number of downloads")


# --- 4. signing up as an individual gets no subdomain -------------------
body, ind_hdrs = register("individual", name="Ada Obi")
assert body["subdomain"] is None, "an individual account must not be given a web address"
ind_tenant = db.query(Tenant).filter_by(id=body["tenant_id"]).one()
assert ind_tenant.account_type == "individual"
assert ind_tenant.subdomain is None

biz_body, biz_hdrs = register("business", name="Acme Industries")
assert biz_body["subdomain"], "a business account must still get its own web address"
assert db.query(Tenant).filter_by(id=biz_body["tenant_id"]).one().account_type == "business"
print("4. OK  an individual gets no subdomain; a business still gets one")


# --- 5. the default, and rubbish, are both business ---------------------
# Everything written before individual accounts existed sends no
# account_type at all, and must keep behaving exactly as it did.
default_body, _ = register()
assert default_body["subdomain"], "a signup that says nothing must stay a business"
assert db.query(Tenant).filter_by(id=default_body["tenant_id"]).one().account_type == "business"
# An unknown value is refused outright rather than quietly coerced - the
# request is wrong, and silently making it a business would hide that.
r = client.post("/auth/register",
                json={"company_name": "Nonsense Co", "email": "nonsense@example.com",
                      "password": "supersecret1", "account_type": "enterprise"},
                headers={"x-forwarded-for": "198.51.100.240"})
assert r.status_code == 422, r.status_code
print("5. OK  a signup that says nothing is a business, and an unknown type is refused")


# --- 6. a tenant from before account types reads as a business ----------
# The additive migration adds the column with a plain ADD COLUMN and no
# default, so every pre-existing row is NULL. NULL is not "unknown", it is
# "created when every account was a business".
legacy_body, legacy_hdrs = register("business", name="Legacy Holdings")
db.execute(text("UPDATE tenants SET account_type = NULL WHERE id = :i"),
           {"i": legacy_body["tenant_id"]})
db.commit()
db.expire_all()
assert db.query(Tenant).filter_by(id=legacy_body["tenant_id"]).one().account_type is None
assert normalize_account_type(None) == "business"
assert client.get("/auth/me", headers=legacy_hdrs).json()["account_type"] == "business"
assert [p.key for p in plans_for_account_type(None)] == list(BUSINESS_PLAN_KEYS)
print("6. OK  a tenant from before this existed reads as a business, never as unknown")


# --- 7. /auth/me reports the account type ------------------------------
assert client.get("/auth/me", headers=ind_hdrs).json()["account_type"] == "individual"
assert client.get("/auth/me", headers=biz_hdrs).json()["account_type"] == "business"
print("7. OK  the signed-in account can tell the frontend which kind it is")


# --- 8. /billing/plans serves the right catalogue ----------------------
# Public and unauthenticated - it backs the marketing pricing section.
all_plans = client.get("/billing/plans").json()
assert {p["key"] for p in all_plans} == set(PLANS), \
    "with no account type asked for, the landing page needs every plan"
biz_only = client.get("/billing/plans?account_type=business").json()
assert [p["key"] for p in biz_only] == list(BUSINESS_PLAN_KEYS)
ind_only = client.get("/billing/plans?account_type=individual").json()
assert [p["key"] for p in ind_only] == list(INDIVIDUAL_PLAN_KEYS)
# An unknown value falls back to everything rather than erroring: this
# endpoint is public and a stale link with a bad query must still render
# a pricing page.
assert {p["key"] for p in client.get("/billing/plans?account_type=nonsense").json()} == set(PLANS)
print("8. OK  /billing/plans serves one catalogue on request and all of them by default")


# --- 9. checkout refuses the other catalogue's plan --------------------
# The heart of it. Without this an individual could buy a 25-seat team
# plan it is not allowed to fill, and a business could be capped at one
# person by a stale link or a hand-made request.
r = client.post("/billing/subscribe", headers=ind_hdrs,
                json={"plan": "pro", "callback_url": "https://app.test/cb",
                      "interval": "monthly"})
assert r.status_code == 400, f"an individual was allowed onto a team plan: {r.text}"
# The refusal names what this account CAN buy, and nothing else - being
# told "no" with no alternative is how a customer gives up rather than pays.
assert "Choose one of: individual_basic, individual_pro, individual_premium" in r.json()["detail"], \
    r.json()["detail"]

r = client.post("/billing/subscribe", headers=biz_hdrs,
                json={"plan": "individual_basic", "callback_url": "https://app.test/cb",
                      "interval": "monthly"})
assert r.status_code == 400, f"a business was allowed onto a one-person plan: {r.text}"

before = len(sent)
assert client.post("/billing/subscribe", headers=ind_hdrs,
                   json={"plan": "nonsense", "callback_url": "https://app.test/cb",
                         "interval": "monthly"}).status_code == 400
assert len(sent) == before, "a refused checkout must not reach Paystack at all"
print("9. OK  neither kind of account can check out on the other's plan")


# --- 10. the right plan does go through -------------------------------
r = client.post("/billing/subscribe", headers=ind_hdrs,
                json={"plan": "individual_basic", "callback_url": "https://app.test/cb",
                      "interval": "monthly"})
assert r.status_code == 200, r.text
assert sent[-1].get("plan") == "PLN_ind_basic_monthly", sent[-1]
assert sent[-1]["amount"] == 350_000, sent[-1]
db.expire_all()
assert db.query(Tenant).filter_by(id=body["tenant_id"]).one().plan == "individual_basic"
print("10. OK  an individual can check out on an individual plan, at the individual price")


# --- 11. an individual cannot invite teammates ------------------------
r = client.post("/auth/team/invite", headers=ind_hdrs,
                json={"email": "friend@example.com", "role": "analyst"})
assert r.status_code == 403, f"an individual was allowed to invite a teammate: {r.text}"
# Deliberately not an upsell: no individual plan has a second seat, so
# "upgrade for more" would be a false promise.
assert "upgrade" not in r.json()["detail"].lower(), \
    "there is no individual plan with a second seat, so this must not offer one"
print("11. OK  an individual cannot invite teammates, and is not sold an upgrade that does not exist")


# --- 12. the subdomain backfill leaves individuals alone --------------
# This runs on EVERY boot and fills in every tenant with no subdomain. Left
# as it was, the next deploy after an individual signed up would quietly
# hand them a web address and undo the decision.
_backfill_tenant_subdomains()
db.expire_all()
assert db.query(Tenant).filter_by(id=body["tenant_id"]).one().subdomain is None, \
    "the backfill gave an individual account a subdomain"
# ...while still repairing a business that is genuinely missing one.
db.execute(text("UPDATE tenants SET subdomain = NULL WHERE id = :i"),
           {"i": biz_body["tenant_id"]})
db.commit()
_backfill_tenant_subdomains()
db.expire_all()
assert db.query(Tenant).filter_by(id=biz_body["tenant_id"]).one().subdomain, \
    "the backfill stopped repairing businesses with no subdomain"
# A tenant predating the column (account_type NULL) is a business and must
# still be repaired - in SQL, NULL != 'individual' is NULL, not true, so a
# naive filter would skip exactly these rows.
db.execute(text("UPDATE tenants SET subdomain = NULL, account_type = NULL WHERE id = :i"),
           {"i": legacy_body["tenant_id"]})
db.commit()
_backfill_tenant_subdomains()
db.expire_all()
assert db.query(Tenant).filter_by(id=legacy_body["tenant_id"]).one().subdomain, \
    "a tenant from before account types was skipped by the backfill"
print("12. OK  the backfill skips individuals and still repairs every business")


# --- 13. a staffer cannot comp across the catalogues ------------------
# Recording a bank transfer or comping an account by hand is the one path
# that bypasses checkout entirely, so it needs the same boundary.
from app.db.models import PlatformStaff
from app.security.auth import hash_password
from app.security.platform_auth import create_platform_access_token

staff = PlatformStaff(email="owner@meridian.example.com",
                      password_hash=hash_password("ownerpass1"), role="owner")
db.add(staff)
db.commit()
STAFF_H = {"Authorization": f"Bearer {create_platform_access_token(staff.id, staff.role)}"}

ind_id, biz_id = body["tenant_id"], biz_body["tenant_id"]
r = client.patch(f"/platform/tenants/{ind_id}", headers=STAFF_H, json={"plan": "premium"})
assert r.status_code == 400, f"a staffer comped an individual onto a team plan: {r.text}"
assert "individual" in r.json()["detail"], r.json()["detail"]
r = client.patch(f"/platform/tenants/{biz_id}", headers=STAFF_H,
                 json={"plan": "individual_premium"})
assert r.status_code == 400, f"a staffer capped a business at one person: {r.text}"
db.expire_all()
assert db.query(Tenant).filter_by(id=ind_id).one().plan == "individual_basic", \
    "a refused staff edit changed the plan anyway"
print("13. OK  a platform staffer cannot comp either kind of account onto the other's plan")


# --- 14. a hand-set "active" with no plan picks the right default -----
# Left as a bare "premium", comping an individual would have handed them a
# 25-seat team plan the rest of the app refuses to let them use.
r = client.patch(f"/platform/tenants/{ind_id}", headers=STAFF_H,
                 json={"subscription_status": "active"})
assert r.status_code == 200, r.text
assert r.json()["plan"] == "individual_basic", \
    "comping should keep the plan the account already had"
assert r.json()["account_type"] == "individual", r.json()
# ...and with no plan at all on the row, the default is the top plan of
# that account's OWN catalogue.
db.execute(text("UPDATE tenants SET plan = NULL WHERE id = :i"), {"i": ind_id})
db.commit()
r = client.patch(f"/platform/tenants/{ind_id}", headers=STAFF_H,
                 json={"subscription_status": "active"})
assert r.status_code == 200, r.text
assert r.json()["plan"] == "individual_premium", \
    f"comping an individual with no plan gave it {r.json()['plan']}"
db.execute(text("UPDATE tenants SET plan = NULL WHERE id = :i"), {"i": biz_id})
db.commit()
r = client.patch(f"/platform/tenants/{biz_id}", headers=STAFF_H,
                 json={"subscription_status": "active"})
assert r.status_code == 200 and r.json()["plan"] == "premium", r.text
print("14. OK  comping an account with no plan defaults to its own catalogue's top plan")


db.close()
print("\nALL INDIVIDUAL ACCOUNT CHECKS PASSED")
