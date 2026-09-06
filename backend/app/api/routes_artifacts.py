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
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import QueryRecord, GeneratedArtifact, Tenant
from app.security.auth import (
    get_current_user, AuthContext,
    create_artifact_download_token, verify_artifact_download_token,
)
from app.agents.export import export_csv, export_xlsx
from app.agents.report_generator import generate_report_pdf
from app.agents.presentation_generator import generate_presentation_pptx
from app.agents.email_delivery import send_report
from app.audit import logger as audit
from app.config import settings
from app.billing.plans import document_limit_for
from app.billing.usage import count_documents_this_month

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _short_title(question: str, limit: int = 100) -> str:
    """A document-only question can be a long, multi-part prompt (a real
    example: a 6-section extraction request with numbered instructions,
    each on its own line) - used verbatim as a report/deck's title, that
    alone can run the entire first page/slide, then get repeated again
    immediately below as the full "Question: ..." line, wasting a whole
    page on pure duplication. The full question is never lost - it's
    always shown in full right below the title in both
    report_generator.py and presentation_generator.py - this only
    shortens the oversized headline sitting on top of it.

    " ".join(question.split()) collapses ALL whitespace runs (spaces,
    tabs, and - critically - the embedded newlines a multi-line/numbered
    question is full of) down to single spaces before truncating. A plain
    .strip() only trims the two ends and leaves internal newlines alone,
    which, cut off mid-question, produced a real, reported bug: a stray
    blank line landing inside the truncated title rendered as if it were
    a second, unrelated bold heading directly under the real one, on both
    the PDF (fpdf2's multi_cell treats an embedded blank line as a
    paragraph break) and the deck (a title placeholder that wraps however
    its own newlines say to). Already-short, single-line questions (the
    common case) come back byte-for-byte unchanged either way."""
    q = " ".join(question.split())
    return q if len(q) <= limit else q[:limit].rstrip() + "…"


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
    # A relative path to the authenticated download route below, already
    # carrying a signed, short-lived token that names this one artifact -
    # NOT a path into a public static directory (that mount is gone; it
    # served every tenant's reports to anyone who could guess a filename).
    # The frontend just prefixes API_BASE and opens it.
    url: str


# Content types for the four artifact kinds _record_artifact writes. Used
# both to set a correct Content-Type on download and, with nosniff, to
# stop a browser from ever interpreting one as HTML/JS.
_MEDIA_TYPES = {
    "report_pdf": "application/pdf",
    "presentation_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "export_csv": "text/csv",
    "export_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# A friendly download filename per kind - the on-disk name is a random
# token and not meaningful to the user.
_DOWNLOAD_NAMES = {
    "report_pdf": "meridian-report.pdf",
    "presentation_pptx": "meridian-presentation.pptx",
    "export_csv": "meridian-export.csv",
    "export_xlsx": "meridian-export.xlsx",
}


def artifact_download_url(a: GeneratedArtifact) -> str:
    return f"/artifacts/file/{a.id}?token={create_artifact_download_token(a.id)}"


def _to_out(a: GeneratedArtifact) -> ArtifactOut:
    return ArtifactOut(id=a.id, kind=a.kind, title=a.title, url=artifact_download_url(a))


@router.get("/file/{artifact_id}")
def download_artifact(artifact_id: str, token: str = "", db: Session = Depends(get_db)):
    """Authenticated artifact download. Auth is the signed `token` query
    param (see app/security/auth.py's create_artifact_download_token) -
    minted only by an endpoint that already checked the caller's tenant
    owns this artifact, valid for one artifact id, short-lived. There is
    deliberately no unauthenticated path here: the previous
    StaticFiles("/artifacts") mount had none, and with 8-hex-char
    filenames that meant any generated report was a guess away from public.
    """
    if verify_artifact_download_token(token) != artifact_id:
        raise HTTPException(403, "This download link is invalid or has expired. Regenerate it from the analysis.")
    artifact = db.query(GeneratedArtifact).filter_by(id=artifact_id).first()
    if not artifact or not os.path.isfile(artifact.file_path):
        raise HTTPException(404, "This artifact is no longer available.")
    return FileResponse(
        artifact.file_path,
        media_type=_MEDIA_TYPES.get(artifact.kind, "application/octet-stream"),
        filename=_DOWNLOAD_NAMES.get(artifact.kind, os.path.basename(artifact.file_path)),
        headers={"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"},
    )


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
        title=f"Analysis: {_short_title(record.question)}", question=record.question,
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
        title=f"Analysis: {_short_title(record.question)}", question=record.question,
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
