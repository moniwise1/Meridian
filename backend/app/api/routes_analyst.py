"""Ask workspace API: confirmed memory, private history, upload findings."""
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import AskMemory, AskFinding, AskScanJob, UploadedDocument, DataSourceConnection, Conversation, QueryRecord, User
from app.security.auth import get_current_user, require_active_subscription, AuthContext
from app.agents.analyst_workspace import memories_for, run_pending_checks, policy_signature, enqueue_upload_check
from app.audit import logger as audit

router = APIRouter(prefix="/ask", tags=["analyst"], dependencies=[Depends(require_active_subscription)])


def authorize_source(db, ctx, key):
    user = db.query(User).filter_by(id=ctx.user_id, tenant_id=ctx.tenant_id).first()
    if not user or "querying" not in (user.capabilities or []):
        raise HTTPException(403, "Querying access is required.")
    kind, _, source_id = key.partition(":")
    if kind == "doc":
        if "document_retrieval" not in (user.capabilities or []):
            raise HTTPException(403, "Document access is required.")
        source = db.query(UploadedDocument).filter_by(id=source_id, tenant_id=ctx.tenant_id).first()
    elif kind == "conn":
        source = db.query(DataSourceConnection).filter_by(id=source_id, tenant_id=ctx.tenant_id).first()
    else:
        raise HTTPException(400, "Choose a valid source.")
    if not source:
        raise HTTPException(404, "Source not found.")
    return source, user


@router.get("/workspace")
def workspace(source_key: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    source, user = authorize_source(db, ctx, source_key)
    conversations = db.query(Conversation).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id).order_by(Conversation.updated_at.desc()).limit(100).all()
    recent = []
    for c in conversations:
        context = c.context or {}
        if context.get("source_key") != source_key:
            continue
        if source_key.startswith("conn:") and context.get("policy_signature") != policy_signature(source, user.row_scope or {}):
            continue
        recent.append({"id": c.id, "title": context.get("last_question", "Conversation")[:120], "updated_at": c.updated_at.isoformat()})
    findings = []
    checks = []
    if source_key.startswith("doc:"):
        if source.user_id == ctx.user_id:
            enqueue_upload_check(db, source)
            db.commit()
        findings = [{"id": f.id, "status": f.status, "source_version": f.source_version, **f.payload}
                    for f in db.query(AskFinding).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, document_id=source.id).order_by(AskFinding.created_at.desc()).limit(20).all()]
        checks = [{"status": j.status, "attempts": j.attempts} for j in db.query(AskScanJob).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, document_id=source.id).all()]
        background_tasks.add_task(run_pending_checks, ctx.tenant_id, ctx.user_id)
    return {"memories": memories_for(db, ctx.tenant_id, ctx.user_id, source_key), "conversations": recent[:20], "findings": findings, "checks": checks}


class MemoryInput(BaseModel):
    source_key: str
    kind: Literal["definition", "correction", "quirk", "seasonality"] = "definition"
    content: str = Field(min_length=1, max_length=1000)


@router.post("/memory")
def save_memory(body: MemoryInput, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    authorize_source(db, ctx, body.source_key)
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "Enter a definition or correction.")
    if db.query(AskMemory).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, source_key=body.source_key).count() >= 30:
        raise HTTPException(400, "Remove an old note before adding another (30 per source).")
    row = AskMemory(tenant_id=ctx.tenant_id, user_id=ctx.user_id, source_key=body.source_key, kind=body.kind, content=content)
    db.add(row)
    audit.log(db, ctx.tenant_id, "ask_memory_confirmed", ctx.user_id, detail={"source_key": body.source_key})
    db.commit()
    return {"id": row.id, "kind": row.kind, "content": row.content, "confirmed": True}


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    row = db.query(AskMemory).filter_by(id=memory_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id).first()
    if not row:
        raise HTTPException(404, "Memory not found.")
    authorize_source(db, ctx, row.source_key)
    db.delete(row)
    audit.log(db, ctx.tenant_id, "ask_memory_removed", ctx.user_id, detail={"memory_id": memory_id})
    db.commit()
    return {"deleted": True}


class FindingUpdate(BaseModel):
    status: Literal["new", "acknowledged", "expected", "dismissed"]


@router.patch("/findings/{finding_id}")
def update_finding(finding_id: str, body: FindingUpdate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    row = db.query(AskFinding).filter_by(id=finding_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id).first()
    if not row:
        raise HTTPException(404, "Finding not found.")
    authorize_source(db, ctx, "doc:" + row.document_id)
    row.status = body.status
    db.commit()
    return {"status": row.status}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    convo = db.query(Conversation).filter_by(id=conversation_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id).first()
    if not convo or not (convo.context or {}).get("source_key"):
        raise HTTPException(404, "Conversation not found.")
    context = convo.context
    source, user = authorize_source(db, ctx, context["source_key"])
    for document_id in context.get("document_ids", []):
        authorize_source(db, ctx, "doc:" + document_id)
    if context["source_key"].startswith("conn:") and context.get("policy_signature") != policy_signature(source, user.row_scope or {}):
        raise HTTPException(403, "Source permissions changed. Start a new analysis with your current access.")
    rows = db.query(QueryRecord).filter_by(conversation_id=convo.id, tenant_id=ctx.tenant_id, user_id=ctx.user_id).order_by(QueryRecord.created_at).limit(100).all()
    return {"id": convo.id, "source_key": context["source_key"], "document_ids": context.get("document_ids", []), "turns": [
        {"question": row.question, "result": {**(row.result_snapshot or {}), "type": "result", "final": True,
         "query_id": row.id, "conversation_id": convo.id, "resolved_question": row.question}} for row in rows]}
