"""
Throwaway end-to-end verification for the run_analysis() conversation_id fix.

Real SQLite metadata DB + real SQLAlchemy Session + the real run_analysis()
generator. Only the external boundaries are stubbed (the warehouse
connector, schema discovery, the SQL-generation LLM call, the insight LLM
call, the follow-up resolver LLM call) - the DB layer under test
(QueryRecord / Conversation creation, flush ordering, commit) is 100% real.

Run from backend/:  python <path-to-this-file>
"""
import os
import tempfile

_tmp = tempfile.mkdtemp()
import base64
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"

import pandas as pd

from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User, DataSourceConnection, QueryRecord, Conversation
from app.connectors.base import QueryResult
from app.agents.context_resolver import ResolvedQuestion
from app.agents.insight_agent import Insight
import app.agents.planner as planner


# ---- stub the external boundaries only -------------------------------------
class _FakeConnector:
    def run_query(self, sql, row_limit, timeout_seconds):
        df = pd.DataFrame(
            {"region": ["South-East", "North-West", "South-West"],
             "revenue": [120000, 90000, 75000]}
        )
        return QueryResult(dataframe=df, duration_ms=12, truncated=False)


class _FakeTable:
    name = "sales"


def _install_stubs():
    planner.build_connector = lambda conn_row: _FakeConnector()
    planner.discover_schema = lambda *a, **k: [_FakeTable()]
    planner.schema_to_prompt_text = lambda tables: "TABLE sales(region TEXT, revenue NUMERIC)"

    class _Gen:
        sql = "SELECT region, revenue FROM sales"
        rationale = "Sum revenue by region."
    planner.generate_sql = lambda *a, **k: _Gen()

    planner.explain = lambda *a, **k: Insight(
        what="South-East leads revenue.", where="South-East", when="current period",
        contributors="South-East", data_quality_caveat="", confidence="medium",
        confidence_explanation="", next_question="What drove South-East?",
    )
    planner.resolve_followup = lambda question, context: ResolvedQuestion(resolved_question=question)
    planner.query_cache.get = lambda *a, **k: None
    planner.query_cache.put = lambda *a, **k: None


def _run(db, tenant_id, user_id, conn_id, question, conversation_id=None):
    final = None
    for event in planner.run_analysis(
        db, tenant_id, user_id, conn_id, question, row_scope={},
        conversation_id=conversation_id,
    ):
        if not isinstance(event, planner.StepEvent):
            final = event
    return final


def main():
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

    # (a) fresh question, no conversation_id
    final1 = _run(db, tenant_id, user_id, conn_id, "Revenue by region?")
    conv_id = final1["conversation_id"]
    rec1 = db.query(QueryRecord).filter_by(id=final1["query_id"]).one()
    conv_rows = db.query(Conversation).all()

    assert conv_id, "final event carried no conversation_id"
    assert len(conv_rows) == 1, f"expected exactly 1 Conversation row, got {len(conv_rows)}"
    assert conv_rows[0].id == conv_id, "final conversation_id != the Conversation row created"
    assert rec1.conversation_id is not None, "BUG: first QueryRecord.conversation_id is NULL"
    assert rec1.conversation_id == conv_id, (
        f"first QueryRecord.conversation_id {rec1.conversation_id!r} != conversation {conv_id!r}"
    )
    import uuid as _uuid
    _uuid.UUID(rec1.conversation_id)  # raises if not a real UUID
    print(f"(a) OK  first QueryRecord.conversation_id = {rec1.conversation_id}")

    # (b) follow-up on that same conversation_id
    final2 = _run(db, tenant_id, user_id, conn_id, "What about North-West?", conversation_id=conv_id)
    rec2 = db.query(QueryRecord).filter_by(id=final2["query_id"]).one()

    assert final2["conversation_id"] == conv_id, "follow-up returned a different conversation_id"
    assert rec2.conversation_id == conv_id, (
        f"follow-up QueryRecord.conversation_id {rec2.conversation_id!r} != {conv_id!r}"
    )
    assert db.query(Conversation).count() == 1, "follow-up created a second Conversation row"
    assert rec1.conversation_id == rec2.conversation_id == conv_id
    print(f"(b) OK  follow-up QueryRecord.conversation_id = {rec2.conversation_id} (same row)")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
