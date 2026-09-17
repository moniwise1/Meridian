"""
Regression guard for the interactive clarification feature: when a
question is genuinely ambiguous in a way that would change the actual
answer, the Ask engine pauses and asks ONE targeted question instead of
guessing or failing outright - bounded so it can never ask a second time
(force_answer=True on the resumed request).

Two layers tested:
1. The real query_generator.generate_sql() / insight_agent.explain_document_only_v2()
   functions against a fake Anthropic client - confirms the defensive
   "never ask again when force_answer is set" behavior holds even if the
   model itself tries to ask again (not just trusting the prompt).
2. planner.py's plumbing (run_analysis / _run_document_only_analysis) via
   the same stubbing style verify_conversation_id_fix.py already uses -
   confirms a ClarificationEvent is yielded and NOTHING is persisted
   (no QueryRecord, no Conversation) when the question is paused, and that
   a normal result still flows through correctly once resumed.

Run from backend/:  python <path-to-this-file>
"""
import base64
import json
import os
import tempfile
from types import SimpleNamespace

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-real")

import pandas as pd

from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User, DataSourceConnection, UploadedDocument, QueryRecord, Conversation
from app.connectors.base import QueryResult
from app.agents.context_resolver import ResolvedQuestion
from app.agents.insight_agent import Insight, DocumentInsight
import app.agents.query_generator as query_generator
import app.agents.insight_agent as insight_agent
import app.agents.planner as planner

# ---------------------------------------------------------------------------
# Layer 1: the real functions against a fake Anthropic client
# ---------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, text: str):
        self._text = text

    def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            stop_reason="end_turn", usage=SimpleNamespace(output_tokens=42),
        )


class _FakeClient:
    def __init__(self, text: str):
        self.messages = _FakeMessages(text)


# --- 1. query_generator.generate_sql: the model asks for clarification,
#        and force_answer=False lets that question through untouched ---
ambiguous_response = json.dumps({
    "sql": "", "rationale": "The metric 'top performers' is ambiguous.",
    "clarification_question": "Do you mean top by revenue or by units sold?",
})
query_generator._client = _FakeClient(ambiguous_response)
result1 = query_generator.generate_sql("Who are the top performers?", "TABLE sales(rep TEXT, revenue NUMERIC, units NUMERIC)")
assert result1.clarification_question == "Do you mean top by revenue or by units sold?", result1
assert result1.sql == "", result1
print("1. OK  generate_sql surfaces the model's clarification_question when force_answer=False")

# --- 2. SAME fake model response, but force_answer=True - the defensive
#        null-out must win even though the model "asked again" ---
result2 = query_generator.generate_sql(
    "Who are the top performers?", "TABLE sales(rep TEXT, revenue NUMERIC, units NUMERIC)", force_answer=True,
)
assert result2.clarification_question is None, result2
print("2. OK  generate_sql never surfaces a clarification_question when force_answer=True, "
      "even if the model tries to ask again")

# --- 3. insight_agent.explain_document_only_v2: same two cases for the
#        document-only path ---
doc_answer_ambiguous = json.dumps({
    "what": "x", "confidence": "low", "confidence_explanation": "",
    "data_quality_caveat": "", "next_question": "",
    "extraction_summary": {}, "key_findings": [], "flagged_items": [], "structured_data": [],
    "clarification_question": "Do you mean this quarter's total or the running annual total?",
})
insight_agent._client = _FakeClient(doc_answer_ambiguous)
insight3, charts3 = insight_agent.explain_document_only_v2(
    "What's the total?", [{"filename": "report.pdf", "kind": "pdf", "text": "..."}],
)
assert insight3.clarification_question == "Do you mean this quarter's total or the running annual total?", insight3
print("3. OK  explain_document_only_v2 surfaces the model's clarification_question when force_answer=False")

insight4, charts4 = insight_agent.explain_document_only_v2(
    "What's the total?", [{"filename": "report.pdf", "kind": "pdf", "text": "..."}], force_answer=True,
)
assert insight4.clarification_question is None, insight4
print("4. OK  explain_document_only_v2 never surfaces a clarification_question when force_answer=True")


# ---------------------------------------------------------------------------
# Layer 2: planner.py's plumbing (stubbed exactly like verify_conversation_id_fix.py)
# ---------------------------------------------------------------------------

class _FakeConnector:
    def run_query(self, sql, row_limit, timeout_seconds):
        df = pd.DataFrame({"region": ["South-East", "North-West"], "revenue": [120000, 90000]})
        return QueryResult(dataframe=df, duration_ms=12, truncated=False)


class _FakeTable:
    name = "sales"


class _StubGeneratedQuery:
    def __init__(self, sql, rationale, clarification_question=None):
        self.sql = sql
        self.rationale = rationale
        self.clarification_question = clarification_question


def _install_stubs():
    planner.build_connector = lambda conn_row: _FakeConnector()
    planner.discover_schema = lambda *a, **k: [_FakeTable()]
    planner.schema_to_prompt_text = lambda tables: "TABLE sales(region TEXT, revenue NUMERIC)"
    planner.resolve_followup = lambda question, context: ResolvedQuestion(resolved_question=question)
    planner.query_cache.get = lambda *a, **k: None
    planner.query_cache.put = lambda *a, **k: None
    # Only exercised by test 6 (the resumed, force_answer=True request that
    # actually reaches SQL execution) - stubbed purely to keep that call
    # from hitting the real (fake-key) Anthropic client and logging an
    # unrelated "insight generation failed" trace that has nothing to do
    # with what this test is actually checking.
    planner.explain = lambda *a, **k: Insight(
        what="Revenue leads.", where="South-East", when="current period",
        contributors="South-East", data_quality_caveat="", confidence="medium",
        confidence_explanation="", next_question="",
    )

    def _fake_generate_sql(question, schema_text, force_answer=False):
        if force_answer:
            return _StubGeneratedQuery(sql="SELECT region, revenue FROM sales", rationale="Assumed revenue.")
        return _StubGeneratedQuery(sql="", rationale="Ambiguous.", clarification_question="Revenue or units?")
    planner.generate_sql = _fake_generate_sql


def _run(db, tenant_id, user_id, conn_id, question, force_answer=False):
    events = []
    final = None
    clarification = None
    for event in planner.run_analysis(
        db, tenant_id, user_id, conn_id, question, row_scope={}, force_answer=force_answer,
    ):
        events.append(event)
        if isinstance(event, planner.ClarificationEvent):
            clarification = event
        elif not isinstance(event, planner.StepEvent):
            final = event
    return events, clarification, final


init_db()
_install_stubs()
db = SessionLocal()
tenant = Tenant(name="Acme"); db.add(tenant); db.flush()
user = User(tenant_id=tenant.id, email="a@acme.test", password_hash="x")
db.add(user); db.flush()
conn = DataSourceConnection(
    tenant_id=tenant.id, name="wh", kind="postgres", host="h", port=5432,
    database="d", username="u", encrypted_password="unused-stubbed",
    column_policy={}, table_allowlist=["sales"],
)
db.add(conn); db.commit()
tenant_id, user_id, conn_id = tenant.id, user.id, conn.id

# --- 5. first ask: the stub says ambiguous -> a ClarificationEvent comes
#        back, no StepEvent/result follows it, and NOTHING is persisted ---
events5, clarification5, final5 = _run(db, tenant_id, user_id, conn_id, "Who are the top performers?")
assert clarification5 is not None and clarification5.question == "Revenue or units?", clarification5
assert final5 is None, "a final result was produced even though the question was ambiguous"
assert events5[-1] is clarification5, "something was yielded after the ClarificationEvent"
assert db.query(QueryRecord).count() == 0, "a QueryRecord was persisted despite pausing for clarification"
assert db.query(Conversation).count() == 0, "a Conversation was persisted despite pausing for clarification"
print("5. OK  an ambiguous question yields a ClarificationEvent, ends the stream there, "
      "and persists nothing")

# --- 6. resumed ask (force_answer=True): the stub answers for real this
#        time -> a normal final result, QueryRecord actually persisted ---
events6, clarification6, final6 = _run(
    db, tenant_id, user_id, conn_id,
    "Who are the top performers?\n\n(Clarifying question: \"Revenue or units?\" — Answer: \"Revenue\")",
    force_answer=True,
)
assert clarification6 is None, "a clarification was asked again despite force_answer=True"
assert final6 is not None and final6["query_id"], final6
assert db.query(QueryRecord).filter_by(id=final6["query_id"]).count() == 1
print("6. OK  the resumed (force_answer=True) request produces a real final result and persists it")


# --- 7 & 8. same two checks, for the document-only path
#            (_run_document_only_analysis) - two documents, so this never
#            touches real table-extraction file I/O ---
def _fake_explain_doc_only(question, document_payload, computed_profile=None, force_answer=False):
    if force_answer:
        return (
            DocumentInsight(
                what="Revenue leads.", confidence="medium", confidence_explanation="Assumed revenue.",
                data_quality_caveat="", next_question="", extraction_summary={}, key_findings=[],
                flagged_items=[], structured_data=[],
            ),
            [],
        )
    return (
        DocumentInsight(
            what="", confidence="low", confidence_explanation="", data_quality_caveat="", next_question="",
            extraction_summary={}, key_findings=[], flagged_items=[], structured_data=[],
            clarification_question="Revenue or units?",
        ),
        [],
    )


planner.explain_document_only_v2 = _fake_explain_doc_only

# Explicit ids: these two are deliberately never added to the session (the
# point is to avoid real file I/O), so the model default that would
# normally assign an id at flush time never runs - and the document-only
# path now names its conversation after documents[0].id.
docs = [
    UploadedDocument(id="clarification-a", tenant_id=tenant_id, filename="a.pdf", kind="pdf", file_path="/nonexistent/a.pdf", extracted_text="..."),
    UploadedDocument(id="clarification-b", tenant_id=tenant_id, filename="b.pdf", kind="pdf", file_path="/nonexistent/b.pdf", extracted_text="..."),
]


def _run_doc(db, tenant_id, user_id, question, force_answer=False):
    query_id = "AQ-doctest"
    events = []
    final = None
    clarification = None
    for event in planner._run_document_only_analysis(
        db, tenant_id, user_id, question, docs, query_id, force_answer=force_answer,
    ):
        events.append(event)
        if isinstance(event, planner.ClarificationEvent):
            clarification = event
        elif not isinstance(event, planner.StepEvent):
            final = event
    return events, clarification, final


events7, clarification7, final7 = _run_doc(db, tenant_id, user_id, "Who are the top performers?")
assert clarification7 is not None and clarification7.question == "Revenue or units?", clarification7
assert final7 is None, "a final result was produced even though the document-only question was ambiguous"
assert events7[-1] is clarification7, "something was yielded after the document-only ClarificationEvent"
assert db.query(QueryRecord).filter_by(id="AQ-doctest").count() == 0, (
    "a QueryRecord was persisted despite pausing for clarification (document-only path)"
)
print("7. OK  document-only: an ambiguous question yields a ClarificationEvent and persists nothing")

events8, clarification8, final8 = _run_doc(
    db, tenant_id, user_id,
    "Who are the top performers?\n\n(Clarifying question: \"Revenue or units?\" — Answer: \"Revenue\")",
    force_answer=True,
)
assert clarification8 is None, "document-only: a clarification was asked again despite force_answer=True"
assert final8 is not None and final8["query_id"] == "AQ-doctest", final8
assert db.query(QueryRecord).filter_by(id="AQ-doctest").count() == 1
print("8. OK  document-only: the resumed (force_answer=True) request produces a real result and persists it")

print("\nALL CLARIFICATION FLOW CHECKS PASSED")
