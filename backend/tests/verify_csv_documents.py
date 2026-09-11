"""
Throwaway verification for CSV document support: document_intelligence.py's
extract_csv (encoding fallback, row-mismatch flagging, truncation) and
tabular_analysis.py's CSV table extraction getting the same deterministic
computed_profile treatment XLSX already has - plus a regression guard for
the deliberate decision NOT to give PDF tables that same trust (see
tabular_analysis.py's module docstring).
Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_csv_documents.py
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from app.agents import document_intelligence, tabular_analysis
from app.agents.document_intelligence import extract, extract_csv, MAX_CSV_ROWS

# --- 1. basic header+rows extraction ---
r = extract_csv(b"Region,Sales\nNorth,100\nSouth,80\n")
assert r.text == "Region | Sales\nNorth | 100\nSouth | 80", r.text
assert r.source_unit_count == 2 and not r.truncated
print("1. OK  basic CSV extraction: header + rows flattened, correct row count")

# --- 2. a row with the wrong column count gets an inline flag, not a crash ---
r2 = extract_csv(b"A,B,C\n1,2,3\n4,5\n6,7,8,9\n")
assert "different column count" in r2.text, r2.text
assert "2 row(s)" in r2.text, r2.text
print("2. OK  mismatched-column rows flagged inline (not crashed on, not silently ignored)")

# --- 3. row-count truncation ---
big_csv = b"N\n" + b"".join(f"{i}\n".encode() for i in range(MAX_CSV_ROWS + 50))
r3 = extract_csv(big_csv)
assert r3.truncated is True
assert f"showing first {MAX_CSV_ROWS}" in r3.text
print("3. OK  a CSV over MAX_CSV_ROWS is truncated with a visible marker, flagged truncated=True")

# --- 4. non-UTF-8 bytes (latin-1 fallback) don't crash the extraction ---
latin1_only = "Café,Prix\nCafé au lait,£3".encode("latin-1")
r4 = extract_csv(latin1_only)
assert "Caf" in r4.text  # decoded, not raised
print("4. OK  non-UTF-8 CSV bytes decode via the latin-1 fallback instead of raising")

# --- 5. extract() dispatches .csv correctly, alongside the existing kinds ---
kind, result = extract("data.csv", b"X,Y\n1,2\n")
assert kind == "csv" and result.source_unit_count == 1
print("5. OK  extract() dispatches a .csv filename to extract_csv")

# --- 6. tabular_analysis: a real numeric CSV produces one usable table
#        with numeric dtypes coerced ---
csv_path = os.path.join(_tmp, "regions.csv")
with open(csv_path, "w", encoding="utf-8") as f:
    f.write("Region,Sales\nNorth,100\nSouth,80\nNorth,50\nSouth,20\nNorth,30\nSouth,60\n")
tables, diagnostics = tabular_analysis.extract_tables(csv_path, "csv")
assert len(tables) == 1, diagnostics
df = tables[0]
assert list(df.columns) == ["Region", "Sales"]
assert df["Sales"].dtype.kind in "if"  # coerced to a real numeric dtype, not left as text
print("6. OK  a real CSV table is parsed with numeric columns coerced, same as XLSX")

# --- 7. a too-small/non-tabular CSV is rejected with a diagnostic, not
#        silently accepted as a usable table ---
tiny_path = os.path.join(_tmp, "tiny.csv")
with open(tiny_path, "w", encoding="utf-8") as f:
    f.write("OnlyOneColumn\njust one row\n")
tables2, diagnostics2 = tabular_analysis.extract_tables(tiny_path, "csv")
assert tables2 == [] and len(diagnostics2) == 1, (tables2, diagnostics2)
print("7. OK  a too-small/non-tabular CSV is rejected with a diagnostic, not silently accepted")

# --- 8. regression guard: PDF tables are STILL never trusted as computed
#        ground truth - this must stay true even after CSV support lands,
#        since computed_profile is the one thing the AI is told never to
#        second-guess (see insight_agent.py's SYSTEM_PROMPT_DOCUMENT_ONLY_V2). ---
pdf_tables, pdf_diagnostics = tabular_analysis.extract_tables("/nonexistent/path.pdf", "pdf")
assert pdf_tables == [] and len(pdf_diagnostics) == 1 and "isn't attempted" in pdf_diagnostics[0], (
    pdf_tables, pdf_diagnostics,
)
print("8. OK  PDF tables still return ([], [diagnostic]) unconditionally - never treated as computed ground truth")

# --- 9. end-to-end through the real planner function: a real uploaded CSV
#        gets the identical deterministic computed_profile-backed chart
#        XLSX already gets - proves the dispatch wiring, not new logic ---
from sqlalchemy.orm import sessionmaker
from app.db.session import engine, init_db
from app.db.models import Tenant, User, UploadedDocument
from app.security.auth import hash_password, create_access_token
from app.agents import insight_agent
from app.agents.planner import _run_document_only_analysis
from types import SimpleNamespace
import json as _json

init_db()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
db = SessionLocal()

t = Tenant(name="CSV Co", subscription_status="none")
db.add(t); db.flush()
u = User(tenant_id=t.id, email="csv@acme.example.com", role="admin", password_hash=hash_password("supersecret1"))
db.add(u); db.commit()

doc = UploadedDocument(
    tenant_id=t.id, user_id=u.id, filename="regions.csv", kind="csv",
    file_path=csv_path, extracted_text="Region | Sales\nNorth | 100\nSouth | 80",
)
db.add(doc); db.commit()


# Answer JSON shaped to satisfy EITHER insight_agent generation this
# might be running against - the pre-existing explain_document_only
# (where/when/contributors are required fields) if this branch predates
# the document-analysis-v2 rebuild landing, or explain_document_only_v2
# (extraction_summary/key_findings) if it doesn't. Either way, this
# test's actual point - CSV gets the same computed_profile chart XLSX
# already gets - is decided entirely in planner.py, not by which insight
# shape is active.
ANSWER = {
    "what": "Sales by region.", "confidence": "high", "confidence_explanation": "Clean data.",
    "data_quality_caveat": "From a real parsed table.", "next_question": "Any outliers?",
    "where": "N/A", "when": "N/A", "contributors": "N/A",
    "extraction_summary": {"total_rows_or_items": 6, "sheets_or_pages_or_slides": 1,
                           "extraction_confidence": "high", "flags": []},
    "key_findings": [], "flagged_items": [], "structured_data": [],
}


class _FakeMessages:
    def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=_json.dumps(ANSWER))],
            stop_reason="end_turn", usage=SimpleNamespace(output_tokens=42),
        )


class _FakeClient:
    messages = _FakeMessages()


insight_agent._client = _FakeClient()
events = list(_run_document_only_analysis(db, t.id, u.id, "Break down sales by region", [doc], "AQ-test-csv"))
final = events[-1]
assert final["final"] is True
# "charts" (document-analysis-v2 rebuild) or "by_group" (pre-rebuild) -
# whichever this branch's planner.py actually produces, it must contain
# the real computed breakdown, not an empty/missing one.
if final.get("charts"):
    chart_rows = final["charts"]
elif final.get("by_group"):
    chart_rows = [{
        "chart_type": "bar", "labels": [r["group"] for r in final["by_group"]],
        "values": [r["total"] for r in final["by_group"]],
    }]
else:
    chart_rows = []
assert len(chart_rows) >= 1, final
real_totals = dict(zip(chart_rows[0]["labels"], chart_rows[0]["values"]))
assert real_totals["North"] == 60.0 and real_totals["South"] == 53.33, real_totals
db.close()
print("9. OK  a real uploaded CSV gets the identical deterministic computed_profile chart XLSX already gets")

print("\nALL CHECKS PASSED")
