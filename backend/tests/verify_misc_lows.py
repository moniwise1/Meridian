"""
Throwaway verification for the misc hardening lows: #21 (uncapped `limit`
query params) and #23 (document upload count cap + pre-read size check).
#24 (MariaDB statement timeout) is code-reviewed only - no MariaDB here.
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, io, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["MAX_DOCUMENTS_PER_TENANT"] = "2"

import docx  # python-docx
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User, AuditLog, UploadedDocument
from app.security.auth import hash_password, create_access_token

init_db()
client = TestClient(app)
db = SessionLocal()
t = Tenant(name="Acme"); db.add(t); db.flush()
u = User(tenant_id=t.id, email="a@acmeco.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()
H = {"Authorization": f"Bearer {create_access_token(u.id, t.id, u.role)}"}


def tiny_docx() -> bytes:
    d = docx.Document()
    d.add_paragraph("Quarterly revenue by region. South-East 120000. North-West 90000.")
    buf = io.BytesIO(); d.save(buf); return buf.getvalue()


# --- 1. uncapped limit params: huge / zero / negative all handled, no error ---
from app.audit import logger as audit_logger
for i in range(5):
    audit_logger.log(db, t.id, f"probe_{i}", u.id)
for q in ["?limit=100000000", "?limit=0", "?limit=-3", ""]:
    r = client.get(f"/audit{q}", headers=H)
    assert r.status_code == 200, (q, r.status_code, r.text)
    assert 0 < len(r.json()) <= 1000, (q, len(r.json()))
r = client.get("/history/analyses?limit=99999999", headers=H)
assert r.status_code == 200 and isinstance(r.json(), list)
r = client.get("/history/artifacts?limit=99999999", headers=H)
assert r.status_code == 200 and isinstance(r.json(), list)
print("1. OK  /audit, /history/analyses, /history/artifacts clamp `limit` (huge/0/negative) - 200, bounded")

# --- 2. document upload count cap ---
r = client.post("/documents/upload", headers=H,
                files={"file": ("q1.docx", tiny_docx(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
assert r.status_code == 200, r.text
r = client.post("/documents/upload", headers=H,
                files={"file": ("q2.docx", tiny_docx(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
assert r.status_code == 200, r.text
assert db.query(UploadedDocument).filter_by(tenant_id=t.id).count() == 2
r = client.post("/documents/upload", headers=H,
                files={"file": ("q3.docx", tiny_docx(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
assert r.status_code == 400 and "stored-document limit" in r.json()["detail"], (r.status_code, r.text)
print("2. OK  3rd upload past MAX_DOCUMENTS_PER_TENANT=2 -> 400")

# --- 3. deleting one frees a slot ---
doc_id = client.get("/documents", headers=H).json()[0]["id"]
assert client.delete(f"/documents/{doc_id}", headers=H).status_code == 200
r = client.post("/documents/upload", headers=H,
                files={"file": ("q4.docx", tiny_docx(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
assert r.status_code == 200, r.text
print("3. OK  deleting a document frees a slot - upload succeeds again")

# --- 4. #24: mysql connector still constructs and its _readonly_conn sets BOTH timeouts ---
import inspect as _inspect
from app.connectors.mysql import MySQLConnector
src = _inspect.getsource(MySQLConnector._readonly_conn)
assert "MAX_EXECUTION_TIME" in src and "max_statement_time" in src, src
print("4. OK  MySQL connector sets both MAX_EXECUTION_TIME (MySQL) and max_statement_time (MariaDB)")

print("\nALL CHECKS PASSED")
