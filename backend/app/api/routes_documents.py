"""
Document upload/list/delete (BUILD SPEC section 19 - document
intelligence). Extraction happens once, at upload time
(app/agents/document_intelligence.py); everything downstream (attaching a
document to a question via /ask/stream) reads the already-extracted,
already-length-capped text stored here, never re-parses the file.

Gated on the "document_retrieval" capability (already in every user's
default capability list, see app/db/models.py) - checked here at upload
time and again in routes_ask.py at ask time, the same defense-in-depth
pattern "querying" already gets: a capability revoked after upload
shouldn't let a stale document_id still be usable in a question.
"""
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User, UploadedDocument
from app.security.auth import get_current_user, AuthContext
from app.agents.document_intelligence import extract, UnsupportedDocumentType
from app.audit import logger as audit
from app.config import settings

router = APIRouter(prefix="/documents", tags=["documents"])


def _require_capability(user: User | None):
    if not user or "document_retrieval" not in (user.capabilities or []):
        raise HTTPException(403, "Your account does not have document retrieval enabled.")


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db),
                           ctx: AuthContext = Depends(get_current_user)):
    user = db.query(User).filter_by(id=ctx.user_id).first()
    _require_capability(user)

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_document_upload_bytes:
        raise HTTPException(
            400, f"File too large ({len(file_bytes)} bytes) — "
                 f"limit is {settings.max_document_upload_bytes} bytes.",
        )

    try:
        kind, extraction = extract(file.filename or "", file_bytes)
    except UnsupportedDocumentType as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        audit.log(db, ctx.tenant_id, "document_upload_failed", ctx.user_id, status="error",
                   detail={"filename": file.filename, "reason": type(e).__name__})
        raise HTTPException(400, f"Could not read this file as a valid document ({type(e).__name__}).")

    os.makedirs(settings.documents_dir, exist_ok=True)
    # Never the caller-supplied filename on disk — that's user-controlled
    # input and this app doesn't need it to be human-readable on disk, only
    # in the DB record shown back to the UI. Avoids any path-traversal
    # surface entirely rather than trying to sanitize it.
    safe_name = f"{uuid.uuid4().hex}.{kind}"
    path = os.path.join(settings.documents_dir, safe_name)
    with open(path, "wb") as f:
        f.write(file_bytes)

    doc = UploadedDocument(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id,
        filename=file.filename or safe_name, kind=kind, file_path=path,
        extracted_text=extraction.text, extraction_truncated=extraction.truncated,
        char_count=len(extraction.text), ocr_pages_used=extraction.ocr_pages_used,
    )
    db.add(doc)
    audit.log(db, ctx.tenant_id, "document_uploaded", ctx.user_id,
               detail={"filename": doc.filename, "kind": kind, "char_count": doc.char_count,
                       "ocr_pages_used": doc.ocr_pages_used})
    db.commit()
    db.refresh(doc)

    return {
        "id": doc.id, "filename": doc.filename, "kind": doc.kind,
        "char_count": doc.char_count, "truncated": doc.extraction_truncated,
        "ocr_pages_used": doc.ocr_pages_used, "created_at": doc.created_at.isoformat(),
    }


@router.get("")
def list_documents(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    rows = (
        db.query(UploadedDocument)
        .filter_by(tenant_id=ctx.tenant_id)
        .order_by(UploadedDocument.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id, "filename": r.filename, "kind": r.kind,
            "char_count": r.char_count, "truncated": r.extraction_truncated,
            "ocr_pages_used": r.ocr_pages_used, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db),
                  ctx: AuthContext = Depends(get_current_user)):
    doc = db.query(UploadedDocument).filter_by(id=document_id, tenant_id=ctx.tenant_id).first()
    if not doc:
        raise HTTPException(404, "Document not found.")
    return {
        "id": doc.id, "filename": doc.filename, "kind": doc.kind,
        "char_count": doc.char_count, "truncated": doc.extraction_truncated,
        "ocr_pages_used": doc.ocr_pages_used,
        "created_at": doc.created_at.isoformat(), "extracted_text": doc.extracted_text,
    }


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db),
                     ctx: AuthContext = Depends(get_current_user)):
    doc = db.query(UploadedDocument).filter_by(id=document_id, tenant_id=ctx.tenant_id).first()
    if not doc:
        raise HTTPException(404, "Document not found.")
    if ctx.role != "admin" and doc.user_id != ctx.user_id:
        raise HTTPException(403, "Only the uploader or an admin can delete this document.")

    try:
        os.remove(doc.file_path)
    except OSError:
        pass  # already gone / never written — deleting the DB record still proceeds
    db.delete(doc)
    audit.log(db, ctx.tenant_id, "document_deleted", ctx.user_id, detail={"filename": doc.filename})
    db.commit()
    return {"status": "deleted"}
