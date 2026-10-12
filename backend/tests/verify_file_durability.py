"""Real SQLite and encrypted bytes survive removal of disposable caches."""
import os
import tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp())
os.environ["APP_SECRET_KEY"] = "dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA="
os.environ["METADATA_DB_URL"] = "sqlite:///" + str(root / "metadata.db")
os.environ["DOCUMENTS_DIR"] = str(root / "documents")
os.environ["ARTIFACTS_DIR"] = str(root / "artifacts")
from fastapi import HTTPException
from app.db.session import init_db, SessionLocal
from app.db.models import StoredFile
from app.file_storage import store_bytes, ensure_file, delete_bytes
from app.config import settings
init_db()
db = SessionLocal()
path = Path(settings.documents_dir) / "sample.csv"
path.parent.mkdir()
content = b"Team,Wait\nSupport,20\nRetail,5\n"
store_bytes(db, "tenant-one", "document", "doc-one", content)
db.commit()
row = db.query(StoredFile).one()
assert content not in row.ciphertext and row.size_bytes == len(row.ciphertext)
assert ensure_file(db, "tenant-one", "document", "doc-one", str(path))
assert path.read_bytes() == content
path.unlink()
db.close()
db = SessionLocal()
assert not ensure_file(db, "tenant-two", "document", "doc-one", str(path))
assert not path.exists()
assert ensure_file(db, "tenant-one", "document", "doc-one", str(path))
assert path.read_bytes() == content
# Legacy originals are copied to durable storage without changing their bytes.
legacy = path.parent / "legacy.txt"
legacy.write_bytes(b"Available original")
assert ensure_file(db, "tenant-one", "document", "legacy", str(legacy))
legacy.unlink()
assert ensure_file(db, "tenant-one", "document", "legacy", str(legacy))
assert legacy.read_bytes() == b"Available original"
assert not ensure_file(db, "tenant-one", "document", "lost", str(path.parent / "missing.txt"))
# Same object cannot be overwritten or reassigned to a different tenant.
for tenant, payload in [("tenant-two",content), ("tenant-one",b"changed")]:
    try: store_bytes(db, tenant, "document", "doc-one", payload)
    except RuntimeError: pass
    else: raise AssertionError("Stored identity was overwritten")
# Cipher integrity failures never materialize unverified bytes.
path.unlink()
row = db.query(StoredFile).filter_by(object_id="doc-one").one()
row.sha256 = "bad"
db.commit()
try: ensure_file(db, "tenant-one", "document", "doc-one", str(path))
except RuntimeError: pass
else: raise AssertionError("Invalid checksum accepted")
assert not path.exists()
delete_bytes(db, "tenant-two", "document", "legacy")
db.commit()
assert db.query(StoredFile).filter_by(object_id="legacy").count() == 1
delete_bytes(db, "tenant-one", "document", "legacy")
db.commit()
assert db.query(StoredFile).filter_by(object_id="legacy").count() == 0
original_limit = settings.max_stored_files_bytes
settings.max_stored_files_bytes = 1
try:
    try: store_bytes(db, "tenant-one", "artifact", "too-full", b"PDF")
    except HTTPException as exc: assert exc.status_code == 413
    else: raise AssertionError("Storage quota bypassed")
finally: settings.max_stored_files_bytes = original_limit
print("Encrypted durability, cache loss, legacy backfill, tenant isolation, integrity, deletion and quotas passed")

# Real upload endpoint and business table reader use durable originals after cache loss.
from fastapi.testclient import TestClient
from app.main import app
from app.db.models import Tenant, User, UploadedDocument
from app.security.auth import create_access_token, AuthContext
from app.api.routes_business import load_source
tenant = Tenant(id="upload-tenant", name="Durability test", subscription_status="active", plan="premium")
user = User(id="upload-user", tenant_id=tenant.id, email="durability@example.com", password_hash="unused", role="admin")
db.add_all([tenant, user]); db.commit()
client = TestClient(app)
headers = {"Authorization": "Bearer " + create_access_token(user.id, tenant.id, user.role)}
uploaded = client.post("/documents/upload", headers=headers, files={"file": ("service.csv", content, "text/csv")})
assert uploaded.status_code == 200, uploaded.text
doc = db.query(UploadedDocument).filter_by(id=uploaded.json()["id"]).one()
assert db.query(StoredFile).filter_by(object_id=doc.id, kind="document").count() == 1
Path(doc.file_path).unlink()
loaded, frame = load_source(db, AuthContext(user.id, tenant.id, user.role), doc.id)
assert frame["Wait"].astype(int).sum() == 25 and Path(doc.file_path).read_bytes() == content
deleted = client.delete("/documents/" + doc.id, headers=headers)
assert deleted.status_code == 200
assert db.query(StoredFile).filter_by(object_id=doc.id, kind="document").count() == 0
print("Real upload, business-view cache restoration and document deletion passed")
