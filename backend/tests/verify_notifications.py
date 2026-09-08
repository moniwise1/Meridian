"""
Throwaway verification for the in-app notification bell + subscription
notices (notification on subscribe, 7-day-before-expiry reminder).
Real SQLite + FastAPI TestClient; only the Paystack HTTP calls are stubbed.
Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_notifications.py
"""
import base64, hashlib, hmac, json, os, tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_fake_secret"
os.environ["PAYSTACK_PLAN_CODE_PRO"] = "PLN_pro"
os.environ["SUBSCRIPTION_REMINDER_SECRET"] = "reminder-secret-xyz"
os.environ["SUBSCRIPTION_EXPIRY_REMINDER_DAYS"] = "7"

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User, Notification
from app.security.auth import hash_password, create_access_token

init_db()
client = TestClient(app)
db = SessionLocal()


def mk_tenant_user(name, email, role="admin"):
    t = Tenant(name=name, subscription_status="none")
    db.add(t); db.flush()
    u = User(tenant_id=t.id, email=email, role=role, password_hash=hash_password("supersecret1"))
    db.add(u); db.commit()
    return t, u, {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def signed_webhook(payload: dict):
    body = json.dumps(payload).encode()
    sig = hmac.new(b"sk_test_fake_secret", body, hashlib.sha512).hexdigest()
    return client.post("/billing/webhook", content=body,
                       headers={"x-paystack-signature": sig, "content-type": "application/json"})


acme, acme_admin, acmeH = mk_tenant_user("Acme Co", "admin@acme.test")
other, other_admin, otherH = mk_tenant_user("Other Co", "admin@other.test")

# --- A. a fresh tenant has an empty bell ---
r = client.get("/notifications", headers=acmeH)
assert r.status_code == 200, (r.status_code, r.text)
assert r.json() == {"notifications": [], "unread_count": 0}, r.json()
print("1. OK  fresh tenant -> empty notifications, unread_count 0")

# --- B. a real subscription activation drops a notice in the bell ---
r = signed_webhook({"event": "charge.success", "data": {
    "reference": "ref-acme", "customer": {"customer_code": "CUS_acme"},
    "plan": {"plan_code": "PLN_pro"}, "metadata": {"tenant_id": acme.id}}})
assert r.status_code == 200, (r.status_code, r.text)

data = client.get("/notifications", headers=acmeH).json()
assert data["unread_count"] == 1, data
assert len(data["notifications"]) == 1, data
n = data["notifications"][0]
assert n["kind"] == "subscription_activated" and n["read"] is False, n
assert n["link"] == "/billing", n
assert "Pro" in n["body"] and "₦9,999" in n["body"], n["body"]
print(f"2. OK  activation -> bell shows {n['kind']!r} (Pro, naira amount, /billing link)")

# --- C. the other tenant sees none of Acme's notifications ---
assert client.get("/notifications", headers=otherH).json() == {"notifications": [], "unread_count": 0}
print("3. OK  notifications are per-tenant/per-user (Other Co sees nothing)")

# --- D. mark-all-read clears the badge ---
r = client.post("/notifications/read", json={"all": True}, headers=acmeH)
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["unread_count"] == 0, r.json()
assert r.json()["notifications"][0]["read"] is True
# still listed, just read
assert client.get("/notifications", headers=acmeH).json()["unread_count"] == 0
print("4. OK  mark-all-read -> unread_count 0, notice still listed as read")

# --- E. the reminder sweep needs the shared secret ---
assert client.post("/notifications/reminders/run").status_code == 401
assert client.post("/notifications/reminders/run",
                   headers={"X-Reminder-Secret": "wrong"}).status_code == 401
print("5. OK  reminder sweep rejects a missing / wrong secret (401)")

# --- F. a subscription expiring in 5 days gets exactly one reminder ---
acme_row = db.query(Tenant).filter_by(id=acme.id).one()
acme_row.subscription_status = "active"
acme_row.subscription_expires_at = datetime.utcnow() + timedelta(days=5)
acme_row.expiry_reminder_sent_for = None
db.commit()

# Other Co: active but not due for 20 days -> must NOT be reminded.
other_row = db.query(Tenant).filter_by(id=other.id).one()
other_row.subscription_status = "active"
other_row.subscription_expires_at = datetime.utcnow() + timedelta(days=20)
db.commit()

r = client.post("/notifications/reminders/run", headers={"X-Reminder-Secret": "reminder-secret-xyz"})
assert r.status_code == 200, (r.status_code, r.text)
assert r.json() == {"checked": 2, "reminded": 1}, r.json()

acme_notes = client.get("/notifications", headers=acmeH).json()
kinds = [x["kind"] for x in acme_notes["notifications"]]
assert "subscription_expiring" in kinds, kinds
assert acme_notes["unread_count"] == 1, acme_notes
assert client.get("/notifications", headers=otherH).json()["unread_count"] == 0, "Other Co wrongly reminded"
db.expire_all()
assert db.query(Tenant).filter_by(id=acme.id).one().expiry_reminder_sent_for is not None
print("6. OK  expiry in 5d -> one reminder to Acme, none to Other Co (due in 20d)")

# --- G. a second sweep the same period is a no-op (idempotent) ---
r = client.post("/notifications/reminders/run", headers={"X-Reminder-Secret": "reminder-secret-xyz"})
assert r.json() == {"checked": 2, "reminded": 0}, r.json()
assert client.get("/notifications", headers=acmeH).json()["unread_count"] == 1, "reminder sent twice"
print("7. OK  second sweep same period -> reminded 0 (once per renewal, not once per day)")

# --- H. a renewal (expiry moves forward) re-arms the reminder ---
acme_row = db.query(Tenant).filter_by(id=acme.id).one()
acme_row.subscription_expires_at = datetime.utcnow() + timedelta(days=4)  # "renewed", new period
db.commit()
r = client.post("/notifications/reminders/run", headers={"X-Reminder-Secret": "reminder-secret-xyz"})
assert r.json() == {"checked": 2, "reminded": 1}, r.json()
# F's reminder (still unread) + H's new one = 2
assert client.get("/notifications", headers=acmeH).json()["unread_count"] == 2, "renewal reminder not added"
print("8. OK  expiry date moved (renewal) -> reminder re-armed and sent once for the new period")

# --- I. cross-tenant write guard on mark-read ---
db.expire_all()
acme_unread = (
    db.query(Notification)
    .filter_by(tenant_id=acme.id, read_at=None)
    .first()
)
assert acme_unread is not None, "expected an unread Acme notification after H"
r = client.post("/notifications/read", json={"ids": [acme_unread.id]}, headers=otherH)
assert r.status_code == 200 and r.json()["unread_count"] == 0, r.json()
db.expire_all()
assert db.query(Notification).filter_by(id=acme_unread.id).one().read_at is None, \
    "Other Co marked Acme's notification read across the tenant boundary"
assert client.get("/notifications", headers=acmeH).json()["unread_count"] == 2
print("9. OK  marking another tenant's notification id read is a silent no-op")

print("\nALL CHECKS PASSED")
