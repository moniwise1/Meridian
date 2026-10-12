"""Known-input metrics and real HTTP authorization checks for executive/owner Ask."""
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

tmp = tempfile.TemporaryDirectory()
os.environ["APP_SECRET_KEY"] = "dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA="
os.environ["METADATA_DB_URL"] = "sqlite:///" + str(Path(tmp.name) / "metadata.db")
os.environ["ARTIFACTS_DIR"] = str(Path(tmp.name) / "artifacts")
os.environ["DOCUMENTS_DIR"] = str(Path(tmp.name) / "documents")
os.environ["ANTHROPIC_API_KEY"] = ""
import pandas as pd
from sqlalchemy import create_engine, text
from fastapi.testclient import TestClient
from app.agents.business_metrics import compute_overview, answer_overview, MetricInputError
from app.security.query_policy import authorize_query, QueryPolicyError
from app.connectors.base import TableSchema, ColumnInfo
from app.security.auth import create_access_token
from app.security.platform_auth import create_platform_access_token
from app.db.models import Tenant, User, UploadedDocument, PlatformStaff, QueryRecord, DataSourceConnection, GeneratedArtifact
from app.agents.analyst_workspace import policy_signature
from app.api.routes_artifacts import artifact_download_url
from app.db.session import SessionLocal
from app.main import app

frame = pd.DataFrame({"date": ["2026-09-30", "2026-10-01", "2026-10-01"], "revenue": ["100.10", "200.20", "0.10"], "expense": ["25", "50", "5"], "currency": ["NGN"] * 3})
mapping = {"date_column": "date", "revenue_column": "revenue", "expense_column": "expense", "currency": "NGN", "currency_column": "currency"}
r = compute_overview(frame, mapping, date(2026, 10, 1), date(2026, 10, 1))
assert r["metrics"][0]["value"] == "200.30"
assert r["metrics"][0]["previous"] == "100.10"
assert r["metrics"][2]["value"] == "145.30"
drill = compute_overview(frame, mapping, date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 1))
assert drill["record_count"] == 3 and drill["detail_count"] == 2
assert drill["records"][0]["source_row"] == 3
assert drill["metrics"][0]["value"] == "300.40"
missing = frame.copy(); missing.loc[1, "revenue"] = None
assert compute_overview(missing, mapping, date(2026, 10, 1), date(2026, 10, 1))["metrics"][0]["value"] is None
mixed = frame.copy(); mixed.loc[1, "currency"] = "USD"
try:
    compute_overview(mixed, mapping, date(2026, 10, 1), date(2026, 10, 1))
    raise AssertionError("mixed currencies accepted")
except MetricInputError:
    pass
empty = compute_overview(frame, mapping, date(2025, 1, 1), date(2025, 1, 1))
assert all(m["value"] is None for m in empty["metrics"])
refund = frame.copy(); refund.loc[2, "revenue"] = "-10.20"
assert compute_overview(refund, mapping, date(2026, 10, 1), date(2026, 10, 1))["metrics"][0]["value"] == "190.00"

# Group comparisons use complete totals from all groups and the same filters.
grouped = frame.copy(); grouped["branch"] = ["A", "A", "B"]
g = compute_overview(grouped, {**mapping, "group_column": "branch"}, date(2026, 10, 1), date(2026, 10, 1))
assert g["group_leaders"]["revenue"]["group"] == "A"
assert "200.20" in answer_overview("Which branch has the highest revenue?", g)
filtered = compute_overview(grouped, {**mapping, "group_column": "branch", "group_value": "B"}, date(2026, 10, 1), date(2026, 10, 1))
assert filtered["metrics"][0]["value"] == "0.10" and filtered["records"][0]["source_row"] == 4
assert "145.30" in answer_overview("What is revenue less mapped expenses?", r)

# Aggregate SQL omits the restricted dimension; the server must still scope it.
schema = [TableSchema("sales", [ColumnInfo("revenue", "NUMERIC"), ColumnInfo("region", "TEXT")])]
engine = create_engine("sqlite://")
with engine.begin() as c:
    c.execute(text("CREATE TABLE sales (revenue NUMERIC, region TEXT, password TEXT)"))
    c.execute(text("INSERT INTO sales VALUES (10, 'Enugu', 'secret'), (90, 'Lagos', 'secret')"))
    for sql in ("SELECT SUM(revenue) AS total FROM sales", "WITH x AS (SELECT * FROM sales) SELECT SUM(revenue) AS total FROM x"):
        authorized = authorize_query(sql, schema, {"region": ["Enugu"]}, 5)
        assert c.execute(text(authorized.sql), authorized.params).scalar() == 10
    authorized = authorize_query("SELECT revenue FROM sales LIMIT 999999", schema, {}, 1)
    assert len(c.execute(text(authorized.sql)).all()) == 1
    authorized = authorize_query("SELECT SUM(revenue) AS total FROM sales", schema, {"region": []}, 5)
    assert c.execute(text(authorized.sql), authorized.params).scalar() is None
for sql in ("SELECT password AS total FROM sales", "SELECT SUM(password) FROM sales", "SELECT * FROM private_table", "SELECT pg_sleep(1) FROM sales"):
    try:
        authorize_query(sql, schema, {}, 10)
        raise AssertionError("unauthorized SQL accepted: " + sql)
    except QueryPolicyError:
        pass
try:
    authorize_query("SELECT NEXT VALUE FOR secret_sequence FROM sales", schema, {}, 5, "mssql")
    raise AssertionError("sequence mutation accepted")
except QueryPolicyError:
    pass
assert "TOP 5" in authorize_query("SELECT revenue FROM sales", schema, {}, 5, "mssql").sql
for kind in ("postgres", "mysql", "mssql", "snowflake"):
    assert authorize_query("SELECT SUM(revenue) AS total FROM sales", schema, {"region": ["Enugu"]}, 5, kind).params

with TestClient(app) as client:
    db = SessionLocal()
    for tid, kind in (("business", "business"), ("individual", "individual"), ("other", "business")):
        db.add(Tenant(id=tid, name=tid, account_type=kind, subscription_status="active", plan="premium"))
        db.add(User(id=tid, tenant_id=tid, email=tid + "@example.invalid", password_hash="unused", role="admin",
                    capabilities=["querying", "document_retrieval"], row_scope={}))
    path = Path(tmp.name) / "source.csv"; frame.to_csv(path, index=False)
    db.add(UploadedDocument(id="source", tenant_id="business", user_id="business", filename="source.csv", kind="csv", file_path=str(path), extracted_text="", char_count=0))
    db.add(PlatformStaff(id="owner", email="owner@example.invalid", password_hash="unused", role="owner"))
    db.add(PlatformStaff(id="support", email="support@example.invalid", password_hash="unused", role="support"))
    db.commit()
    def headers(tid):
        return {"Authorization": "Bearer " + create_access_token(tid, tid, "admin")}
    body = {**mapping, "document_id": "source", "start": "2026-10-01", "end": "2026-10-01", "question": "What is revenue?"}
    assert client.post("/business/overview", json=body).status_code == 401
    assert client.post("/business/overview", json=body, headers=headers("individual")).status_code == 403
    assert client.post("/business/overview", json=body, headers=headers("other")).status_code == 404
    response = client.post("/business/overview", json=body, headers=headers("business"))
    assert response.status_code == 200, response.text
    assert response.json()["metrics"][0]["value"] == "200.30"
    assert "200.30" in response.json()["answer"]
    excel_path = Path(tmp.name) / "source.xlsx"; frame.to_excel(excel_path, index=False)
    db.add(UploadedDocument(id="source-excel", tenant_id="business", user_id="business", filename="source.xlsx",
        kind="xlsx", file_path=str(excel_path), extracted_text="", char_count=0))
    db.commit()
    excel_response = client.post("/business/overview", json={**body, "document_id": "source-excel"}, headers=headers("business"))
    assert excel_response.status_code == 200, excel_response.text
    assert excel_response.json()["metrics"][0]["value"] == "200.30"
    # A colleague in the same tenant cannot open or export a private result.
    db.add(User(id="colleague", tenant_id="business", email="colleague@example.invalid", password_hash="unused",
                role="analyst", capabilities=["querying", "document_retrieval"], row_scope={}))
    connection = DataSourceConnection(id="warehouse", tenant_id="business", name="Warehouse", kind="postgres",
        host="example.invalid", port=5432, database="data", username="readonly", encrypted_password="unused",
        table_allowlist=["sales"], column_policy={})
    db.add(connection); db.flush()
    db.add(QueryRecord(id="private-analysis", tenant_id="business", user_id="business", connection_id="warehouse",
        question="Revenue?", generated_sql="SELECT SUM(revenue) FROM sales", result_snapshot={"policy_signature": policy_signature(connection, {}), "metrics": {"total": 10}}, row_count=1))
    export_path = Path(tmp.name) / "private.csv"; export_path.write_text("total\n10\n")
    artifact = GeneratedArtifact(id="private-export", tenant_id="business", user_id="business", source_query_id="private-analysis",
        kind="export_csv", title="Private export", file_path=str(export_path))
    db.add(artifact); db.commit()
    colleague = {"Authorization": "Bearer " + create_access_token("colleague", "business", "analyst")}
    assert client.get("/history/analyses/private-analysis", headers=colleague).status_code == 404
    assert client.post("/artifacts/export/private-analysis", headers=colleague).status_code == 404
    assert client.get("/history/artifacts", headers=colleague).json() == []
    signed_url = artifact_download_url(artifact)
    assert client.get(signed_url).status_code == 200
    connection.table_allowlist = ["sales", "additional_table"]; db.commit()
    assert client.get("/history/analyses/private-analysis", headers=headers("business")).status_code == 403
    assert client.get(signed_url).status_code == 403
    # Revoking unrestricted document access also blocks old Ask conversations/text.
    business_user = db.get(User, "business"); business_user.row_scope = {"region": ["Enugu"]}; db.commit()
    assert client.get("/documents/source", headers=headers("business")).status_code == 403
    assert client.post("/business/overview", json=body, headers=headers("business")).status_code == 403
    assert client.post("/platform/ask", json={"question": "How many signups?"}, headers=headers("business")).status_code == 401
    for staff, status in (("owner", 200), ("support", 403)):
        h = {"Authorization": "Bearer " + create_platform_access_token(staff, staff)}
        response = client.post("/platform/ask", json={"question": "How many signups?"}, headers=h)
        assert response.status_code == status, response.text
        if status == 200:
            assert "password" not in response.text and "extracted_text" not in response.text
    db.close()
print("Executive metrics, SQL boundaries, saved-result revocation, business and owner Ask checks passed")
