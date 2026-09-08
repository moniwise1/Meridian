"""
Throwaway verification for security fix #13 - raw exception strings must
not reach the client from /ask/stream, /scan/stream, or the insight step.
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
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User, DataSourceConnection
from app.security.auth import hash_password, create_access_token
import app.api.routes_ask as routes_ask
import app.api.routes_scan as routes_scan

SECRET_STR = "psql://admin:SUPERSECRETPW@10.0.0.5:5432/prod -- SELECT * FROM users.ssn"

init_db()
client = TestClient(app)
db = SessionLocal()
t = Tenant(name="Acme", subscription_status="active", plan="premium"); db.add(t); db.flush()
u = User(tenant_id=t.id, email="a@acmeco.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
conn = DataSourceConnection(tenant_id=t.id, name="wh", kind="postgres", host="h", port=5432,
                             database="d", username="u", encrypted_password="x",
                             column_policy={}, table_allowlist=["sales"])
db.add(conn); db.commit()
H = {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def sse_details(resp):
    out = []
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            import json
            out.append(json.loads(line[5:].strip()))
    return out


# --- 1. /ask/stream: run_analysis blows up with a sensitive message ---
def _boom(*a, **k):
    raise RuntimeError(SECRET_STR)
    yield  # make it a generator
routes_ask.run_analysis = _boom
r = client.post("/ask/stream", headers=H, json={"connection_id": conn.id, "question": "hi"})
events = sse_details(r)
err = [e for e in events if e.get("status") == "error"]
assert err, events
blob = r.text
assert SECRET_STR not in blob and "10.0.0.5" not in blob and "SUPERSECRETPW" not in blob, \
    f"raw exception leaked to client:\n{blob}"
assert "failed unexpectedly" in err[-1]["detail"], err[-1]
print("1. OK  /ask/stream hides the raw exception, returns a generic message")

# --- 2. /scan/stream: same ---
def _boom_scan(*a, **k):
    raise RuntimeError(SECRET_STR)
routes_scan.build_connector = _boom_scan
r = client.post("/scan/stream", headers=H, json={"connection_id": conn.id})
blob = r.text
assert SECRET_STR not in blob and "SUPERSECRETPW" not in blob, f"leaked:\n{blob}"
assert "failed unexpectedly" in blob, blob
print("2. OK  /scan/stream hides the raw exception, returns a generic message")

# --- 3. insight step failure message is generic (planner.py) ---
import app.agents.planner as planner
from app.agents.context_resolver import ResolvedQuestion
import pandas as pd
from app.connectors.base import QueryResult

class _FakeConn:
    def run_query(self, *a, **k):
        return QueryResult(dataframe=pd.DataFrame({"region": ["SE"], "revenue": [1]}), duration_ms=1, truncated=False)
class _FakeTbl:
    name = "sales"

planner.build_connector = lambda cr: _FakeConn()
planner.discover_schema = lambda *a, **k: [_FakeTbl()]
planner.schema_to_prompt_text = lambda x: "sales(region, revenue)"
planner.generate_sql = lambda *a, **k: type("G", (), {"sql": "SELECT region, revenue FROM sales", "rationale": "r"})()
planner.resolve_followup = lambda q, c: ResolvedQuestion(resolved_question=q)
planner.query_cache.get = lambda *a, **k: None
planner.query_cache.put = lambda *a, **k: None
def _explain_boom(*a, **k):
    raise RuntimeError("anthropic error: invalid x-api-key sk-ant-SECRET123 for account foo")
planner.explain = _explain_boom

final = None
for ev in planner.run_analysis(db, t.id, u.id, conn.id, "revenue?", row_scope={}):
    if not isinstance(ev, planner.StepEvent):
        final = ev
assert final and "error" in final["insight"], final
msg = final["insight"]["error"]
assert "sk-ant" not in msg and "invalid x-api-key" not in msg and "anthropic" not in msg.lower(), msg
assert "temporarily unavailable" in msg, msg
print(f"3. OK  insight-failure message is generic: {msg!r}")

print("\nALL CHECKS PASSED")
