"""
Report / presentation / export / email endpoints (BUILD SPEC sections 22,
23, 24). Every one of these operates on a QueryRecord that already belongs
to the caller's tenant and already passed the output-security check when it
was first run - generating an artifact is not a second, less-checked path
to the underlying data. "Email this to me" resolves the recipient from the
authenticated user, never from client input, per section 23.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import QueryRecord, GeneratedArtifact, Tenant
from app.security.auth import get_current_user, AuthContext
from app.agents.export import export_csv, export_xlsx
from app.agents.report_generator import generate_report_pdf
from app.agents.presentation_generator import generate_presentation_pptx
from app.agents.email_delivery import send_report
from app.audit import logger as audit
from app.config import settings
from app.billing.plans import document_limit_for
from app.billing.usage import count_documents_this_month

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _get_query_record(db: Session, tenant_id: str, query_id: str) -> QueryRecord:
    row = db.query(QueryRecord).filter_by(id=query_id, tenant_id=tenant_id).first()
    if not row:
        raise HTTPException(404, "Analysis not found.")
    return row


def _record_artifact(db: Session, ctx: AuthContext, kind: str, title: str,
                      query_id: str, path: str) -> GeneratedArtifact:
    artifact = GeneratedArtifact(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, kind=kind, title=title,
        source_query_id=query_id, file_path=path,
    )
    db.add(artifact)
    audit.log(db, ctx.tenant_id, f"artifact_generated:{kind}", ctx.user_id, query_id=query_id,
               detail={"title": title})
    db.commit()
    db.refresh(artifact)
    return artifact


class ArtifactOut(BaseModel):
    id: str
    kind: str
    title: str
    url: str


def _to_out(a: GeneratedArtifact) -> ArtifactOut:
    return ArtifactOut(id=a.id, kind=a.kind, title=a.title,
                        url=f"/artifacts/{os.path.basename(a.file_path)}")


def _require_capability(db: Session, ctx: AuthContext, capability: str):
    from app.db.models import User
    user = db.query(User).filter_by(id=ctx.user_id).first()
    if not user or capability not in (user.capabilities or []):
        raise HTTPException(403, f"Your account does not have '{capability}' enabled.")


def _check_document_limit(db: Session, ctx: AuthContext):
    """Shared monthly cap across report/presentation/export (see
    app/billing/plans.py's document_limit docstring) - a plan limit, not a
    permissions error, hence 402, matching every other plan-limit check in
    this app."""
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    limit = document_limit_for(tenant.plan if tenant and tenant.tier == "pro" else None)
    if limit is not None and count_documents_this_month(db, ctx.tenant_id) >= limit:
        raise HTTPException(
            402,
            f"Your plan's monthly limit of {limit} report/presentation downloads has been "
            f"reached. Upgrade on the Billing page for more.",
        )


@router.post("/report/{query_id}", response_model=ArtifactOut)
def create_report(query_id: str, db: Session = Depends(get_db),
                   ctx: AuthContext = Depends(get_current_user)):
    _require_capability(db, ctx, "report_generation")
    _check_document_limit(db, ctx)
    record = _get_query_record(db, ctx.tenant_id, query_id)
    snap = record.result_snapshot
    path = generate_report_pdf(
        title=f"Analysis: {record.question}", question=record.question,
        insight=snap.get("insight", {}), metrics=snap.get("metrics", {}),
        by_group=snap.get("by_group"), data_quality=snap.get("data_quality", {}),
        anomalies=snap.get("anomalies", []), sql=snap.get("sql", record.generated_sql),
        query_id=record.id,
    )
    artifact = _record_artifact(db, ctx, "report_pdf", f"Report — {record.question[:60]}", query_id, path)
    return _to_out(artifact)


@router.post("/presentation/{query_id}", response_model=ArtifactOut)
def create_presentation(query_id: str, db: Session = Depends(get_db),
                         ctx: AuthContext = Depends(get_current_user)):
    _require_capability(db, ctx, "presentation_generation")
    _check_document_limit(db, ctx)
    record = _get_query_record(db, ctx.tenant_id, query_id)
    snap = record.result_snapshot
    path = generate_presentation_pptx(
        title=f"Analysis: {record.question}", question=record.question,
        insight=snap.get("insight", {}), metrics=snap.get("metrics", {}),
        by_group=snap.get("by_group"), data_quality=snap.get("data_quality", {}),
        anomalies=snap.get("anomalies", []), query_id=record.id,
    )
    artifact = _record_artifact(db, ctx, "presentation_pptx", f"Presentation — {record.question[:60]}", query_id, path)
    return _to_out(artifact)


@router.post("/export/{query_id}", response_model=ArtifactOut)
def create_export(query_id: str, format: str = "csv", db: Session = Depends(get_db),
                   ctx: AuthContext = Depends(get_current_user)):
    _check_document_limit(db, ctx)
    record = _get_query_record(db, ctx.tenant_id, query_id)
    rows = record.result_snapshot.get("preview_rows", [])
    if not rows:
        raise HTTPException(400, "No rows available to export for this analysis.")
    if format == "xlsx":
        path = export_xlsx(rows, "export")
        kind = "export_xlsx"
    else:
        path = export_csv(rows, "export")
        kind = "export_csv"
    artifact = _record_artifact(db, ctx, kind, f"Export — {record.question[:60]}", query_id, path)
    return _to_out(artifact)


class EmailRequest(BaseModel):
    query_id: str
    recipient: EmailStr
    artifact_id: str | None = None
    confirmed: bool = False


@router.post("/email")
def email_artifact(body: EmailRequest, db: Session = Depends(get_db),
                    ctx: AuthContext = Depends(get_current_user)):
    record = _get_query_record(db, ctx.tenant_id, body.query_id)
    attachment_path = None
    if body.artifact_id:
        artifact = db.query(GeneratedArtifact).filter_by(id=body.artifact_id, tenant_id=ctx.tenant_id).first()
        if artifact:
            attachment_path = artifact.file_path

    result = send_report(
        db, ctx.tenant_id, ctx.user_id, body.recipient,
        subject=f"Analysis: {record.question[:80]}",
        body=record.result_snapshot.get("insight", {}).get("what", "See attached analysis."),
        attachment_path=attachment_path, artifact_id=body.artifact_id, confirmed=body.confirmed,
    )
    if result.status == "blocked":
        raise HTTPException(403, result.reason)
    return {"status": result.status, "reason": result.reason}
