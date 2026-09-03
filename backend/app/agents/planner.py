"""
Planner / Orchestrator (BUILD SPEC sections 10, 12, 18, 20).

Runs the full pipeline for one question:
  resolve follow-up context -> understand -> discover schema -> generate SQL
  -> validate -> execute -> check output policy -> assess quality
  -> compute metrics -> detect anomalies -> investigate -> explain
  -> update conversation context

Prompt-injection defence (section 20): the only text that ever reaches the
LLM as "instructions" is our own SYSTEM_PROMPT strings in query_generator.py
/ insight_agent.py / context_resolver.py. Retrieved data (schema field
names, row values, and — since document intelligence — text extracted from
a user-uploaded document) is always passed as a separate JSON/user-content
payload, never concatenated into instruction text, and its content can
never expand table/column access beyond what schema_discovery already
filtered.

tenant_id/user_id/row_scope all come from the caller having already
resolved them from a verified auth token (see api/routes_ask.py) - this
module never trusts a client-supplied identity.
"""
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import DataSourceConnection, QueryRecord, Conversation, UploadedDocument
from app.security.secrets import decrypt, RedactedSecret
from app.security.query_validator import validate_readonly_sql
from app.security.output_guard import check_dataframe
from app.connectors.postgres import PostgresConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.mssql import MSSQLConnector
from app.agents.schema_discovery import discover_schema, schema_to_prompt_text
from app.agents.query_generator import generate_sql
from app.agents.data_quality import assess
from app.agents.analytics_engine import summarize
from app.agents.insight_agent import explain
from app.agents.anomaly_detection import detect as detect_anomalies
from app.agents.investigation import investigate_cascade
from app.agents.forecasting import forecast_by_group
from app.agents.context_resolver import resolve as resolve_followup, build_context_snapshot
from app.agents import query_cache
from app.agents.column_heuristics import guess_columns
from app.audit import logger as audit
from app.config import settings


@dataclass
class StepEvent:
    step: str
    status: str  # "running" | "done" | "error"
    detail: str = ""


class PolicyViolation(Exception):
    pass


_CONNECTOR_REGISTRY = {"postgres": PostgresConnector, "mysql": MySQLConnector, "mssql": MSSQLConnector}


def build_connector(conn_row: DataSourceConnection):
    password = RedactedSecret(decrypt(conn_row.encrypted_password))
    connector_cls = _CONNECTOR_REGISTRY.get(conn_row.kind)
    if connector_cls is None:
        raise ValueError(f"Unsupported connector kind: {conn_row.kind}")
    return connector_cls(
        host=conn_row.host, port=conn_row.port, database=conn_row.database,
        username=conn_row.username, password=password,
        timeout_seconds=settings.query_timeout_seconds,
    )


def _json_safe(records: list[dict]) -> list[dict]:
    """SQLAlchemy's JSON column type needs plain JSON-serializable values;
    pandas can hand back Timestamps/Decimals/numpy scalars that aren't."""
    import json
    return json.loads(json.dumps(records, default=str))


def run_analysis(db: Session, tenant_id: str, user_id: str, connection_id: str,
                  question: str, row_scope: dict, conversation_id: str | None = None,
                  document_ids: list[str] | None = None):
    """Generator yielding StepEvent progress, ending with a final dict result."""
    query_id = f"AQ-{uuid.uuid4().hex[:8]}"

    # Re-resolved against this tenant, never trusting that a client-supplied
    # document_id actually belongs here - same "never trust an id the
    # client handed us" discipline as everything else in this module.
    documents = []
    if document_ids:
        documents = (
            db.query(UploadedDocument)
            .filter(UploadedDocument.id.in_(document_ids), UploadedDocument.tenant_id == tenant_id)
            .all()
        )

    conn_row = db.query(DataSourceConnection).filter_by(id=connection_id, tenant_id=tenant_id).first()
    if not conn_row:
        yield StepEvent("understanding", "error", "Connection not found or not authorized for this tenant.")
        return

    conversation = None
    if conversation_id:
        conversation = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id, user_id=user_id).first()

    resolved_question = question
    if conversation and conversation.context:
        resolved = resolve_followup(question, conversation.context)
        resolved_question = resolved.resolved_question
        if resolved_question != question:
            yield StepEvent("understanding", "done", f"{question}  ->  {resolved_question}")
        else:
            yield StepEvent("understanding", "done", question)
    else:
        yield StepEvent("understanding", "done", question)

    # Cache lookup: only for fresh (non-follow-up) questions with no
    # attached documents - see app/agents/query_cache.py for why follow-ups
    # are excluded. Documents are excluded for the same reason: the cached
    # insight would have been shaped by whatever document text was attached
    # when it was computed, and the cache key doesn't account for that.
    if conversation_id is None and not document_ids:
        cached = query_cache.get(
            tenant_id, connection_id, conn_row.table_allowlist, conn_row.column_policy,
            row_scope, resolved_question,
        )
        if cached is not None:
            yield StepEvent("finding_data", "done", "Served from cache.")
            yield StepEvent(
                "running_analysis", "done",
                "An identical question (same data source, same access scope) was asked "
                "recently — reusing that result instead of re-running the query.",
            )
            yield StepEvent("checking_quality", "done", "")
            yield StepEvent("investigating_drivers", "done", "")
            yield StepEvent("preparing_insights", "done", "")

            # A fresh QueryRecord either way, so this shows up as its own
            # entry in Analyses history and "Create from this analysis"
            # (report/presentation/export) still works from a real,
            # independently-generated report_generation of the underlying
            # snapshot. No Conversation row is created here, so a cached
            # answer can't be chained into a follow-up directly - ask a new
            # question to continue, which runs fresh.
            db.add(QueryRecord(
                id=query_id, tenant_id=tenant_id, user_id=user_id, connection_id=connection_id,
                conversation_id=None, question=resolved_question, generated_sql=cached["sql"],
                row_count=cached["row_count"], duration_ms=cached["duration_ms"],
                result_snapshot=cached,
            ))
            audit.log(db, tenant_id, "query_served_from_cache", user_id, connection_id, query_id,
                      {"row_count": cached["row_count"]})
            db.commit()

            yield {
                "final": True,
                "query_id": query_id,
                "conversation_id": None,
                "resolved_question": resolved_question,
                **cached,
            }
            return

    connector = build_connector(conn_row)

    yield StepEvent("finding_data", "running")
    tables = discover_schema(connector, conn_row.table_allowlist or None, conn_row.column_policy or {})
    if not tables:
        yield StepEvent("finding_data", "error", "No authorized tables available for this connection.")
        return
    schema_text = schema_to_prompt_text(tables)
    if row_scope:
        schema_text += "\n\nMANDATORY FILTER (row-level policy — always include as a WHERE condition): " + \
            ", ".join(f"{k} IN ({', '.join(repr(v) for v in vals)})" for k, vals in row_scope.items())
    yield StepEvent("finding_data", "done", f"{len(tables)} authorized table(s) available.")

    yield StepEvent("running_analysis", "running")
    generated = generate_sql(resolved_question, schema_text)
    if not generated.sql:
        yield StepEvent("running_analysis", "error", generated.rationale or "Could not translate question to an authorized query.")
        return

    validation = validate_readonly_sql(generated.sql, settings.default_row_limit)
    if not validation.is_valid:
        audit.log(db, tenant_id, "query_rejected", user_id, connection_id, query_id,
                   {"reason": validation.reason}, status="denied")
        yield StepEvent("running_analysis", "error", f"Query rejected by policy: {validation.reason}")
        return

    result = connector.run_query(validation.normalized_sql, settings.default_row_limit, settings.query_timeout_seconds)
    df = result.dataframe

    allowed_cols = None
    table_hint = tables[0].name if len(tables) == 1 else None
    if table_hint and conn_row.column_policy.get(table_hint):
        allowed_cols = set(conn_row.column_policy[table_hint])

    output_check = check_dataframe(df, allowed_cols, max_raw_rows=settings.max_row_limit)
    if not output_check.allowed:
        audit.log(db, tenant_id, "output_blocked", user_id, connection_id, query_id,
                   {"reason": output_check.reason}, status="denied")
        yield StepEvent("running_analysis", "error", f"Output blocked by policy: {output_check.reason}")
        return

    # Row-level scope enforcement: verify returned values don't escape the user's allowed scope.
    for scope_col, allowed_vals in (row_scope or {}).items():
        if scope_col in df.columns:
            offending = set(df[scope_col].dropna().unique()) - set(allowed_vals)
            if offending:
                audit.log(db, tenant_id, "row_scope_violation", user_id, connection_id, query_id,
                           {"column": scope_col}, status="denied")
                raise PolicyViolation(f"Result includes rows outside your authorized scope for '{scope_col}'.")

    yield StepEvent("running_analysis", "done", f"{len(df)} row(s) analysed.")

    yield StepEvent("checking_quality", "running")
    quality = assess(df)
    yield StepEvent("checking_quality", "done", "; ".join(quality.notes) or "No data quality issues detected.")

    value_col, group_col, date_col = guess_columns(list(df.columns))
    metrics = summarize(df, value_col=value_col, group_col=group_col, date_col=date_col)

    yield StepEvent("investigating_drivers", "running")
    anomalies = detect_anomalies(df, value_col, group_col, date_col)
    investigation_results = []
    if anomalies and value_col and group_col:
        # Investigate only the single most significant anomaly, cascading
        # through further dimensions (top contributor -> next dimension ->
        # its top contributor -> ...) rather than stopping one level deep -
        # bounded by MAX_CASCADE_DEPTH so this can never run an unbounded
        # number of extra queries.
        top_anomaly = anomalies[0]
        investigation_results = investigate_cascade(
            connector, tables, schema_text, top_anomaly, group_col, value_col,
            row_limit=settings.default_row_limit, timeout_seconds=settings.query_timeout_seconds,
        )
    if anomalies:
        detail = "; ".join(a.what for a in anomalies[:3])
        yield StepEvent("investigating_drivers", "done", detail)
    else:
        yield StepEvent("investigating_drivers", "done", "No significant anomalies detected.")

    yield StepEvent("forecasting", "running")
    forecasts = forecast_by_group(df, value_col, group_col, date_col)
    if forecasts:
        yield StepEvent(
            "forecasting", "done",
            "; ".join(f"{f.group} trending {f.trend_direction}" for f in forecasts[:3]),
        )
    else:
        yield StepEvent("forecasting", "done", "Not enough historical periods to project a trend.")

    yield StepEvent("preparing_insights", "running")
    insight_metrics = dict(metrics.summary)
    if anomalies:
        insight_metrics["anomalies"] = [asdict(a) for a in anomalies[:3]]
    if investigation_results:
        insight_metrics["investigation"] = [
            {"dimension": r.dimension, "breakdown": r.breakdown[:5]} for r in investigation_results
        ]
    document_payload = [
        {"filename": d.filename, "kind": d.kind, "text": d.extracted_text} for d in documents
    ] or None
    try:
        insight = explain(resolved_question, insight_metrics, quality.notes, document_payload)
        insight_dict = asdict(insight)
    except Exception as e:
        insight_dict = {"error": f"Insight generation unavailable: {e}"}
    yield StepEvent("preparing_insights", "done")

    # Single snapshot dict, reused for the persisted QueryRecord, the cache
    # entry (fresh questions only), and the streamed final event - one
    # source of truth so those three can never quietly drift apart.
    snapshot = {
        "sql": validation.normalized_sql,
        "sql_rationale": generated.rationale,
        "row_count": len(df),
        "duration_ms": result.duration_ms,
        "truncated": result.truncated,
        "metrics": metrics.summary,
        "by_group": metrics.by_group,
        "insight": insight_dict,
        "data_quality": asdict(quality),
        "anomalies": [asdict(a) for a in anomalies],
        "investigation": [{"dimension": r.dimension, "breakdown": r.breakdown} for r in investigation_results],
        "forecast": [asdict(f) for f in forecasts],
        "documents_used": [d.filename for d in documents],
        "preview_rows": _json_safe(df.head(20).to_dict(orient="records")) if allowed_cols is not False else [],
    }

    db.add(QueryRecord(
        id=query_id, tenant_id=tenant_id, user_id=user_id, connection_id=connection_id,
        conversation_id=conversation.id if conversation else None,
        question=question, generated_sql=validation.normalized_sql,
        row_count=len(df), duration_ms=result.duration_ms,
        result_snapshot=snapshot,
    ))
    audit.log(db, tenant_id, "query_executed", user_id, connection_id, query_id,
              {"row_count": len(df), "duration_ms": result.duration_ms, "table": table_hint})

    if not conversation:
        conversation = Conversation(
            tenant_id=tenant_id, user_id=user_id, connection_id=connection_id, context={},
        )
        db.add(conversation)
    conversation.context = build_context_snapshot(
        resolved_question, table_hint, value_col, group_col, date_col, metrics.by_group,
    )
    conversation.updated_at = datetime.utcnow()
    db.commit()

    if conversation_id is None:
        query_cache.put(
            tenant_id, connection_id, conn_row.table_allowlist, conn_row.column_policy,
            row_scope, resolved_question, snapshot,
        )

    yield {
        "final": True,
        "query_id": query_id,
        "conversation_id": conversation.id,
        "resolved_question": resolved_question,
        **snapshot,
    }
