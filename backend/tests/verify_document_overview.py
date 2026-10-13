"""Real parsing, scoped access and durable-cache restore."""
import os
import tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp())
os.environ['APP_SECRET_KEY'] = 'dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA='
os.environ['METADATA_DB_URL'] = 'sqlite:///' + str(root / 'metadata.db')
os.environ['DOCUMENTS_DIR'] = str(root / 'documents')
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User, UploadedDocument
from app.security.auth import create_access_token
init_db()
db = SessionLocal()
db.add_all([Tenant(id='a',name='A'), Tenant(id='b',name='B')]); db.flush()
u = User(tenant_id='a',email='a@example.invalid',password_hash='disabled',role='admin')
v = User(tenant_id='b',email='b@example.invalid',password_hash='disabled',role='admin')
db.add_all([u,v]); db.commit()
headers = lambda user: {'Authorization':'Bearer ' + create_access_token(user.id,user.tenant_id,user.role)}
client = TestClient(app)
r = client.post('/documents/upload',headers=headers(u),files={'file':('test.csv',b'Store,Wait\nA,10\nB,20\nB,20\nC,\n','text/csv')})
assert r.status_code == 200, r.text
identifier = r.json()['id']
path = Path(db.query(UploadedDocument).filter_by(id=identifier).one().file_path)
path.unlink()
r = client.get(f'/documents/{identifier}/overview',headers=headers(u))
assert r.status_code == 200, r.text
p = r.json()
assert p['row_count'] == 4 and p['missing_cells'] == 1 and p['duplicate_rows'] == 1, p
assert '"Wait"' in p['suggested_questions'][0]
assert all('sample' not in f for f in p['fields']) and path.exists()
assert client.get(f'/documents/{identifier}/overview',headers=headers(v)).status_code == 404
u.row_scope = {'region':'West'}; db.commit()
assert client.get(f'/documents/{identifier}/overview',headers=headers(u)).status_code == 403
u.row_scope = {}; u.capabilities = []; db.commit()
assert client.get(f'/documents/{identifier}/overview',headers=headers(u)).status_code == 403
print('File overview parsing, counts, durable restore and authorization passed')

from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from app.agents.document_overview import overview
stub = SimpleNamespace(extraction_truncated=True, file_path="unused", kind="txt")
with patch("app.agents.tabular_analysis.extract_tables",return_value=([],["Text-only file"])):
    text = overview(stub)
    assert text["mode"] == "text" and text["row_count"] is None and text["fields"] == []
    assert any("50,000" in note for note in text["notes"])
frame = pd.DataFrame({"Store":[" ","A","B"], "Wait":[float("inf"),1,2]})
with patch("app.agents.tabular_analysis.extract_tables",return_value=([frame,frame],[])):
    table = overview(stub)
    assert table["missing_cells"] == 2
    assert any("2 usable tables" in note for note in table["notes"])
print("Text fallback, multi-table scope, non-finite and blank-value checks passed")
