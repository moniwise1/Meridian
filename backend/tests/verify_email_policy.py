"""
Throwaway verification for security fix #14 - tenant-level outbound-email policy.
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User
from app.security.auth import hash_password, create_access_token
from app.agents.email_delivery import send_report

init_db()
client = TestClient(app)
db = SessionLocal()


def mk(role="admin", email="admin@acmeco.com"):
    t = Tenant(name="Acme"); db.add(t); db.flush()
    u = User(tenant_id=t.id, email=email, role=role, password_hash=hash_password("supersecret1"))
    db.add(u); db.commit()
    return t, u, {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def send(t, u, to, confirmed):
    return send_report(db, t.id, u.id, to, "s", "b", None, None, confirmed).status


# --- 1. default 'open' (new tenant, and a NULL-policy legacy row) ---
t, u, H = mk()
assert send(t, u, "admin@acmeco.com", False) == "sent"            # self always ok
assert send(t, u, "x@external.com", False) == "pending_confirmation"
assert send(t, u, "x@external.com", True) == "sent"
t.outbound_email_policy = None; db.commit()                       # simulate a pre-migration row
assert send(t, u, "x@external.com", True) == "sent"
print("1. OK  'open' (incl. NULL legacy) - self ok, external needs confirm then sends")

# --- 2. self_only ---
r = client.patch("/auth/team/email-policy", headers=H, json={"mode": "self_only", "allowed_domains": []})
assert r.status_code == 200, r.text
db.expire_all()
assert send(t, u, "admin@acmeco.com", True) == "sent"
assert send(t, u, "x@external.com", True) == "blocked"
print("2. OK  self_only - own address sends, every external recipient blocked (even confirmed)")

# --- 3. domain_allowlist ---
r = client.patch("/auth/team/email-policy", headers=H,
                 json={"mode": "domain_allowlist", "allowed_domains": ["Acme.com", "@partner.co"]})
assert r.status_code == 200 and r.json()["allowed_domains"] == ["acme.com", "partner.co"], r.text
db.expire_all()
assert send(t, u, "cfo@acme.com", True) == "sent"
assert send(t, u, "ext@partner.co", True) == "sent"
assert send(t, u, "leak@evil.com", True) == "blocked"
assert send(t, u, "admin@acmeco.com", True) == "sent"            # self still ok regardless
print("3. OK  domain_allowlist - listed domains + self send, others blocked; domains normalized")

# --- 4. PATCH validation ---
assert client.patch("/auth/team/email-policy", headers=H,
                    json={"mode": "nonsense", "allowed_domains": []}).status_code == 400
assert client.patch("/auth/team/email-policy", headers=H,
                    json={"mode": "domain_allowlist", "allowed_domains": []}).status_code == 400
assert client.patch("/auth/team/email-policy", headers=H,
                    json={"mode": "domain_allowlist", "allowed_domains": ["not a domain"]}).status_code == 400
print("4. OK  bad mode / empty allowlist / malformed domain all -> 400")

# --- 5. non-admin: can read, cannot change ---
t2, u2, H2 = mk(role="analyst", email="analyst@acmeco.com")
assert client.get("/auth/team/email-policy", headers=H2).status_code == 200
assert client.patch("/auth/team/email-policy", headers=H2,
                    json={"mode": "self_only", "allowed_domains": []}).status_code == 403
print("5. OK  non-admin can GET the policy but PATCH -> 403")

print("\nALL CHECKS PASSED")
