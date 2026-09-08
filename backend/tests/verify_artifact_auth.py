"""
Throwaway verification for authenticated artifact downloads (security fix #1).
Real SQLite + real FastAPI TestClient. Run from backend/:
    PYTHONPATH=$(pwd) python <this file>
"""
import base64, os, tempfile, time

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Tenant, User, QueryRecord, GeneratedArtifact
from app.security.auth import (
    hash_password, create_access_token,
    create_artifact_download_token, ARTIFACT_DOWNLOAD_TTL_SECONDS,
)
import app.security.auth as auth_mod

init_db()
client = TestClient(app)

db = SessionLocal()
t = Tenant(name="Acme", subscription_status="active", plan="premium"); db.add(t); db.flush()
u = User(tenant_id=t.id, email="a@acmeco.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
tok = create_access_token(u.id, t.id, u.role)
H = {"Authorization": f"Bearer {tok}"}

# Seed a QueryRecord so we can generate a real report through the real endpoint.
qr = QueryRecord(
    id="AQ-testq1", tenant_id=t.id, user_id=u.id, connection_id="conn-x", conversation_id=None,
    question="Revenue by region?", generated_sql="SELECT region, revenue FROM sales",
    row_count=3, duration_ms=10,
    result_snapshot={
        "sql": "SELECT region, revenue FROM sales", "sql_rationale": "sum by region",
        "insight": {"what": "South-East leads.", "where": "South-East", "when": "Q",
                     "contributors": "SE", "data_quality_caveat": "", "confidence": "medium",
                     "confidence_explanation": "", "next_question": "why?"},
        "metrics": {"total": 285000}, "by_group": [{"group": "South-East", "total": 120000}],
        "data_quality": {"row_count": 3, "completeness_pct": 100.0, "duplicate_pct": 0.0,
                          "missing_by_column": {}, "outlier_notes": [], "excluded_row_count": 0, "notes": []},
        "anomalies": [], "investigation": [], "forecast": [], "documents_used": [], "preview_rows": [],
    },
)
db.add(qr); db.commit()

# --- full happy path: generate -> download via the returned url ---
r = client.post("/artifacts/report/AQ-testq1", headers=H)
assert r.status_code == 200, (r.status_code, r.text)
art = r.json()
assert art["url"].startswith("/artifacts/file/"), art["url"]
assert "token=" in art["url"], art["url"]
print(f"1. OK  generate returns authenticated url: {art['url'][:55]}...")

dl = client.get(art["url"], headers={})  # no bearer - the signed token in the url is the auth
assert dl.status_code == 200, (dl.status_code, dl.text)
assert dl.headers["content-type"] == "application/pdf", dl.headers["content-type"]
assert dl.headers.get("x-content-type-options") == "nosniff"
assert dl.content[:4] == b"%PDF", dl.content[:16]
assert "attachment" in dl.headers.get("content-disposition", ""), dl.headers.get("content-disposition")
print(f"2. OK  signed url downloads the real PDF ({len(dl.content)} bytes, nosniff, attachment)")

artifact_id = art["url"].split("/artifacts/file/")[1].split("?")[0]

# --- negative cases ---
assert client.get(f"/artifacts/file/{artifact_id}").status_code == 403          # no token
assert client.get(f"/artifacts/file/{artifact_id}?token=garbage").status_code == 403
# token for a DIFFERENT artifact id must not work here
other = create_artifact_download_token("some-other-artifact-id")
assert client.get(f"/artifacts/file/{artifact_id}?token={other}").status_code == 403
print("3. OK  missing / malformed / wrong-artifact tokens all 403")

# --- expired token ---
real_time = time.time
try:
    auth_mod.time.time = lambda: real_time() - ARTIFACT_DOWNLOAD_TTL_SECONDS - 60
    stale = create_artifact_download_token(artifact_id)
finally:
    auth_mod.time.time = real_time
assert client.get(f"/artifacts/file/{artifact_id}?token={stale}").status_code == 403
print("4. OK  expired token 403")

# --- the old unauthenticated static mount is gone ---
disk_name = os.path.basename(db.query(GeneratedArtifact).filter_by(id=artifact_id).one().file_path)
assert len(disk_name.split("-")[-1].split(".")[0]) == 32, disk_name  # full uuid hex, not [:8]
gone = client.get(f"/artifacts/{disk_name}")
assert gone.status_code == 404, (gone.status_code, "old static path still serves files!")
print(f"5. OK  old static path /artifacts/{disk_name[:20]}... -> 404 (mount removed); filename is full-length")

# --- history listing also uses the authenticated url ---
hist = client.get("/history/artifacts", headers=H)
assert hist.status_code == 200, hist.text
assert hist.json(), "expected the generated artifact in history"
assert hist.json()[0]["url"].startswith("/artifacts/file/") and "token=" in hist.json()[0]["url"]
hist_dl = client.get(hist.json()[0]["url"])
assert hist_dl.status_code == 200 and hist_dl.content[:4] == b"%PDF"
print("6. OK  /history/artifacts url is authenticated and downloads")

print("\nALL CHECKS PASSED")
