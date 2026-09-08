"""
Throwaway verification for security fixes #15 (security headers) and #17
(/docs off in production). Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, subprocess, sys, tempfile, textwrap

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User, DataSourceConnection
from app.security.auth import hash_password, create_access_token
import app.api.routes_ask as routes_ask

init_db()
client = TestClient(app)

# --- 1. every response carries the safe header set ---
r = client.get("/health")
h = r.headers
assert h.get("x-content-type-options") == "nosniff", dict(h)
assert h.get("x-frame-options") == "DENY", dict(h)
assert h.get("referrer-policy") == "no-referrer", dict(h)
assert h.get("cross-origin-opener-policy") == "same-origin", dict(h)
assert "strict-transport-security" not in h, "HSTS must not be sent over plain http"
print("1. OK  nosniff / DENY / no-referrer / COOP present on a plain response; no HSTS over http")

# --- 2. HSTS appears when the request is (forwarded) https ---
r = client.get("/health", headers={"x-forwarded-proto": "https"})
assert r.headers.get("strict-transport-security", "").startswith("max-age=63072000"), dict(r.headers)
print("2. OK  HSTS present when X-Forwarded-Proto=https")

# --- 3. dev mode keeps the docs ---
assert client.get("/docs").status_code == 200
assert client.get("/openapi.json").status_code == 200
print("3. OK  /docs + /openapi.json available in development")

# --- 4. SSE streaming still works through the header middleware ---
def _boom(*a, **k):
    yield routes_ask.StepEvent("understanding", "done", "x")
    yield {"final": True, "query_id": "AQ-x", "conversation_id": None, "resolved_question": "x"}
routes_ask.run_analysis = _boom
db = SessionLocal()
t = Tenant(name="Acme", subscription_status="active", plan="premium"); db.add(t); db.flush()
u = User(tenant_id=t.id, email="a@acmeco.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
conn = DataSourceConnection(tenant_id=t.id, name="c", kind="postgres", host="h", port=5432,
                             database="d", username="u", encrypted_password="x",
                             column_policy={}, table_allowlist=["s"])
db.add(conn); db.commit()
H = {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}
r = client.post("/ask/stream", headers=H, json={"connection_id": conn.id, "question": "hi"})
assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"], (r.status_code, dict(r.headers))
assert '"final": true' in r.text.lower() and r.headers.get("x-content-type-options") == "nosniff", r.text[:200]
print("4. OK  /ask/stream still streams SSE, and carries the security headers")

# --- 5. production mode: docs are gone (separate process, ENVIRONMENT=production) ---
prog = textwrap.dedent(f"""
    import os
    os.environ["APP_SECRET_KEY"] = {os.environ['APP_SECRET_KEY']!r}
    os.environ["ENVIRONMENT"] = "production"
    os.environ["JWT_SECRET_KEY"] = "distinct-jwt-secret"
    os.environ["PLATFORM_JWT_SECRET"] = "distinct-platform-secret"
    os.environ["KMS_PROVIDER"] = "local"   # not aws -> validate_startup_config would fail on boot,
    os.environ["METADATA_DB_URL"] = {os.environ['METADATA_DB_URL']!r}
    os.environ["ARTIFACTS_DIR"] = {os.environ['ARTIFACTS_DIR']!r}
    os.environ["DOCUMENTS_DIR"] = {os.environ['DOCUMENTS_DIR']!r}
    from fastapi.testclient import TestClient
    from app.main import app          # import builds the app with docs_url=None
    c = TestClient(app)               # does NOT run startup (no 'with'), so validate_startup_config is skipped
    assert c.get("/docs").status_code == 404, "docs should be 404 in production"
    assert c.get("/redoc").status_code == 404
    assert c.get("/openapi.json").status_code == 404
    print("5. OK  production: /docs, /redoc, /openapi.json all 404")
""")
res = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": os.getcwd()})
sys.stdout.write(res.stdout)
assert res.returncode == 0, res.stderr

print("\nALL CHECKS PASSED")
