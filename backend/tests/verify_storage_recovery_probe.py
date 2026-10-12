"""Synthetic probe drives real API endpoints, then loses caches and cleans up."""
import os
import tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp())
os.environ["APP_SECRET_KEY"] = "dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA="
os.environ["METADATA_DB_URL"] = "sqlite:///" + str(root / "metadata.db")
os.environ["DOCUMENTS_DIR"] = str(root / "documents")
os.environ["ARTIFACTS_DIR"] = str(root / "artifacts")
from unittest.mock import patch
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, StoredFile, UploadedDocument, GeneratedArtifact
from scripts import storage_recovery_probe as probe
init_db()
client = TestClient(app)
class LocalSession:
    def __init__(self, **kwargs):
        assert kwargs == {'trust_env':False, 'follow_redirects':False}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def post(self, url, **kwargs):
        assert url.startswith('http://127.0.0.1:')
        kwargs.pop('timeout', None)
        parsed = urlsplit(url)
        return client.post(parsed.path, **kwargs)
    def get(self, url, **kwargs):
        assert url.startswith('http://127.0.0.1:')
        kwargs.pop('timeout', None)
        parsed = urlsplit(url)
        return client.get(parsed.path + ('?' + parsed.query if parsed.query else ''), **kwargs)
db = SessionLocal()
db.add(Tenant(id='real-customer-sentinel', name='Must remain untouched')); db.commit()
with patch.object(probe.httpx, 'Client', LocalSession):
    result = probe.run(db, 'create')
    assert result['durable_objects'] == 2 and result['original_bytes_match']
    identifier = result['probe_id']
    for row in db.query(UploadedDocument).filter_by(tenant_id=identifier): Path(row.file_path).unlink()
    for row in db.query(GeneratedArtifact).filter_by(tenant_id=identifier): Path(row.file_path).unlink()
    verified = probe.run(db, 'verify', identifier)
    assert verified['both_caches_missing_before_restore'] and verified['original_bytes_match']
    try: probe.run(db, 'cleanup', 'real-customer-sentinel')
    except RuntimeError: pass
    else: raise AssertionError('Probe cleanup touched an unrelated tenant')
    assert probe.run(db, 'cleanup', identifier)['cleanup'] == 'complete'
assert db.query(Tenant).filter_by(id='real-customer-sentinel').count() == 1
assert db.query(Tenant).filter_by(id=identifier).count() == 0
assert db.query(StoredFile).filter_by(tenant_id=identifier).count() == 0
print('Synthetic authenticated upload, PDF generation, cache recovery and scoped cleanup passed')
