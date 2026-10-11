"""Saved results remain private and cannot outlive changed source permissions."""
from fastapi import HTTPException
from app.db.models import User, DataSourceConnection, UploadedDocument
from app.agents.analyst_workspace import policy_signature


def check_analysis_access(db, record, user_id):
    if not record or record.user_id != user_id:
        raise HTTPException(404, "Analysis not found.")
    user = db.query(User).filter_by(id=user_id, tenant_id=record.tenant_id).first()
    if not user or "querying" not in (user.capabilities or []):
        raise HTTPException(403, "Analysis access is not enabled.")
    snap = record.result_snapshot or {}
    if record.connection_id == "document-only":
        if "document_retrieval" not in (user.capabilities or []) or user.row_scope:
            raise HTTPException(403, "Document analysis access is unavailable under your current permissions.")
        ids = snap.get("source_document_ids", [])
        if ids and db.query(UploadedDocument).filter(UploadedDocument.id.in_(ids), UploadedDocument.tenant_id == record.tenant_id).count() != len(ids):
            raise HTTPException(403, "An analysis source is no longer available.")
    else:
        connection = db.query(DataSourceConnection).filter_by(id=record.connection_id, tenant_id=record.tenant_id).first()
        if not connection:
            raise HTTPException(403, "The analysis source is no longer available.")
        stored = snap.get("policy_signature")
        if stored:
            if stored != policy_signature(connection, user.row_scope or {}):
                raise HTTPException(403, "Source permissions changed. Run a new analysis.")
        elif user.row_scope or connection.table_allowlist or connection.column_policy:
            raise HTTPException(403, "This legacy analysis needs to be rerun under current permissions.")
    return record
