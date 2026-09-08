"""
Throwaway verification for security fix #8 - SSRF guard on data-source
connection hosts. Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from app.config import settings
from app.security.ssrf import check_connection_host, BlockedHostError


def blocked(host):
    try:
        check_connection_host(host)
        return False
    except BlockedHostError:
        return True


# --- 1. unit: private / loopback / link-local / CGNAT / metadata all blocked ---
for h in ["127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.5.5", "169.254.169.254",
          "100.100.100.100", "0.0.0.0", "::1", "fd00::1", "localhost"]:
    assert blocked(h), f"{h} should be blocked"
print("1. OK  loopback / RFC1918 / link-local / CGNAT / metadata / localhost / IPv6 ULA all blocked")

# --- 2. a public address is allowed ---
for h in ["8.8.8.8", "1.1.1.1"]:
    assert not blocked(h), f"{h} should be allowed"
print("2. OK  public IPs allowed")

# --- 3. unresolvable host is blocked (fail closed) ---
assert blocked("no-such-host.invalid")
print("3. OK  unresolvable host blocked (fail closed)")

# --- 4. the opt-out flag disables the check ---
settings.allow_private_connection_hosts = True
assert not blocked("127.0.0.1")
settings.allow_private_connection_hosts = False
print("4. OK  ALLOW_PRIVATE_CONNECTION_HOSTS disables the guard")

# --- 5. end-to-end: POST /connections with an internal host -> 400 ---
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User, AuditLog
from app.security.auth import hash_password, create_access_token

init_db()
client = TestClient(app)
db = SessionLocal()
t = Tenant(name="Acme", subscription_status="active", plan="premium"); db.add(t); db.flush()
u = User(tenant_id=t.id, email="a@acmeco.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
H = {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}
payload = dict(name="internal", kind="postgres", port=5432, database="d", username="u", password="p")

r = client.post("/connections", headers=H, json={**payload, "host": "169.254.169.254"})
assert r.status_code == 400 and "non-public" in r.json()["detail"], (r.status_code, r.text)
assert db.query(AuditLog).filter_by(action="connection_host_blocked").count() == 1
print("5. OK  POST /connections host=169.254.169.254 -> 400 + audit 'connection_host_blocked'")

# --- 6. a public host gets PAST the SSRF check (fails later, at connect) ---
r = client.post("/connections", headers=H, json={**payload, "host": "8.8.8.8"})
assert r.status_code == 400 and "could not connect" in r.json()["detail"].lower(), (r.status_code, r.text)
print("6. OK  public host passes SSRF, then fails at test_connection (not over-blocking)")

print("\nALL CHECKS PASSED")
