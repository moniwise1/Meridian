"""
Throwaway verification for security fix #5 — /billing/verify must bind a
payment reference to the caller's own tenant. Real SQLite + FastAPI TestClient.
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, hashlib, hmac, json, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake_secret"
os.environ["PAYSTACK_PLAN_CODE_BASIC"] = "PLN_basic"
os.environ["PAYSTACK_PLAN_CODE_PRO"] = "PLN_pro"
os.environ["PAYSTACK_PLAN_CODE_PREMIUM"] = "PLN_premium"

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User
from app.security.auth import hash_password, create_access_token
from app.billing import paystack

init_db()
client = TestClient(app)
db = SessionLocal()


def mk_tenant_user(name, email, ref=None, plan=None):
    t = Tenant(name=name, subscription_status="pending" if ref else "none",
               plan=plan, last_transaction_reference=ref)
    db.add(t); db.flush()
    u = User(tenant_id=t.id, email=email, role="admin", password_hash=hash_password("supersecret1"))
    db.add(u); db.commit()
    return t, u, {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


# Victim tenant started a real checkout for "basic" -> reference "ref-victim".
victim, vu, vH = mk_tenant_user("Victim Co", "a@victimco.com", ref="ref-victim", plan="basic")
# Attacker tenant: also started a checkout, reference "ref-attacker".
attacker, au, aH = mk_tenant_user("Attacker Co", "a@attackerco.com", ref="ref-attacker", plan="basic")

# Paystack says both references succeeded; victim's was actually for premium.
_TXNS = {
    "ref-victim": {"status": "success", "reference": "ref-victim",
                    "customer": {"customer_code": "CUS_v"}, "plan": {"plan_code": "PLN_premium"},
                    "metadata": {"tenant_id": victim.id}},
    "ref-attacker": {"status": "success", "reference": "ref-attacker",
                      "customer": {"customer_code": "CUS_a"}, "plan": {"plan_code": "PLN_basic"},
                      "metadata": {"tenant_id": attacker.id}},
}
paystack.verify_transaction = lambda reference, client=None: dict(_TXNS[reference])

# --- A. attacker replays the VICTIM's reference -> must be rejected ---
r = client.get("/billing/verify?reference=ref-victim", headers=aH)
assert r.status_code == 403, (r.status_code, r.text)
db.expire_all()
assert db.query(Tenant).filter_by(id=attacker.id).one().subscription_status != "active", \
    "attacker got activated off the victim's payment reference!"
print("1. OK  replaying another tenant's reference -> 403, attacker NOT activated")

# --- B. victim verifies their own reference -> activates, plan reconciled ---
r = client.get("/billing/verify?reference=ref-victim", headers=vH)
assert r.status_code == 200, (r.status_code, r.text)
db.expire_all()
v = db.query(Tenant).filter_by(id=victim.id).one()
assert v.subscription_status == "active", v.subscription_status
assert v.plan == "premium", f"plan not reconciled from verified txn: {v.plan!r} (was 'basic' pre-checkout)"
print(f"2. OK  own reference verifies -> active, plan reconciled to '{v.plan}' from the verified transaction")

# --- C. a tenant with no recorded checkout reference -> 403 for anything ---
fresh, fu, fH = mk_tenant_user("Fresh Co", "a@freshco.com", ref=None)
paystack.verify_transaction = lambda reference, client=None: {
    "status": "success", "reference": reference, "plan": {"plan_code": "PLN_premium"}, "customer": {}}
r = client.get("/billing/verify?reference=anything-at-all", headers=fH)
assert r.status_code == 403, (r.status_code, r.text)
print("3. OK  tenant with no started checkout -> 403")

# --- D. the webhook path still works and is unaffected ---
attacker2, _, _ = mk_tenant_user("Webhook Co", "a@webhookco.com", ref="ref-wh", plan="basic")
body = json.dumps({"event": "charge.success", "data": {
    "reference": "ref-wh", "customer": {"customer_code": "CUS_wh"},
    "plan": {"plan_code": "PLN_pro"}, "metadata": {"tenant_id": attacker2.id}}}).encode()
sig = hmac.new(b"sk_test_fake_secret", body, hashlib.sha512).hexdigest()
r = client.post("/billing/webhook", content=body,
                headers={"x-paystack-signature": sig, "content-type": "application/json"})
assert r.status_code == 200, (r.status_code, r.text)
db.expire_all()
w = db.query(Tenant).filter_by(id=attacker2.id).one()
assert w.subscription_status == "active" and w.plan == "pro", (w.subscription_status, w.plan)
print("4. OK  signed charge.success webhook still activates the right tenant and reconciles plan")

# --- E. webhook with a bad signature still rejected ---
r = client.post("/billing/webhook", content=body,
                headers={"x-paystack-signature": "deadbeef", "content-type": "application/json"})
assert r.status_code == 401, (r.status_code, r.text)
print("5. OK  bad webhook signature -> 401")

print("\nALL CHECKS PASSED")
