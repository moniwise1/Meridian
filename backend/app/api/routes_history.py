"""
Analyses and artifacts history — read-only browsing of what has already run
or been generated (the spec's Analyses history / Reports library /
Presentations library nav). No new capability is exposed here: every row
returned already passed through /ask or /artifacts and its tenant scoping
when it was first created. Tenant-scoped rather than user-scoped, matching
the audit log's convention — a team sees each other's analyses and
artifacts, same as it already sees each other's audit trail.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import QueryRecord, GeneratedArtifact, PinnedAnalysis
from app.security.auth import get_current_user, AuthContext

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/analyses")
def list_analyses(limit: int = 50, pinned_only: bool = False, db: Session = Depends(get_db),
                   ctx: AuthContext = Depends(get_current_user)):
    # Pins are per-user (see PinnedAnalysis's docstring), so which rows show
    # a filled star - and which rows `pinned_only` even considers - depends
    # on who's asking, unlike everything else on this tenant-scoped endpoint.
    pinned_ids = {
        p.query_id for p in
        db.query(PinnedAnalysis).filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id).all()
    }
    q = db.query(QueryRecord).filter_by(tenant_id=ctx.tenant_id)
    if pinned_only:
        if not pinned_ids:
            return []
        q = q.filter(QueryRecord.id.in_(pinned_ids))
    rows = q.order_by(QueryRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "query_id": r.id,
            "question": r.question,
            "connection_id": r.connection_id,
            "row_count": r.row_count,
            "duration_ms": r.duration_ms,
            "pinned": r.id in pinned_ids,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.put("/analyses/{query_id}/pin")
def pin_analysis(query_id: str, db: Session = Depends(get_db),
                  ctx: AuthContext = Depends(get_current_user)):
    """Idempotent: pinning an already-pinned analysis is a no-op, not a
    duplicate-row error - the frontend toggles this on a single click
    without needing to track prior state itself."""
    if not db.query(QueryRecord).filter_by(id=query_id, tenant_id=ctx.tenant_id).first():
        raise HTTPException(404, "Analysis not found.")
    existing = (
        db.query(PinnedAnalysis)
        .filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, query_id=query_id)
        .first()
    )
    if not existing:
        db.add(PinnedAnalysis(tenant_id=ctx.tenant_id, user_id=ctx.user_id, query_id=query_id))
        db.commit()
    return {"pinned": True}


@router.delete("/analyses/{query_id}/pin")
def unpin_analysis(query_id: str, db: Session = Depends(get_db),
                    ctx: AuthContext = Depends(get_current_user)):
    existing = (
        db.query(PinnedAnalysis)
        .filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, query_id=query_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
    return {"pinned": False}


@router.get("/analyses/{query_id}")
def get_analysis(query_id: str, db: Session = Depends(get_db),
                  ctx: AuthContext = Depends(get_current_user)):
    """Reconstructs the same shape /ask/stream's final event produces, so the
    frontend can reopen a past analysis in the same ResultView component
    used for a freshly-run one."""
    r = db.query(QueryRecord).filter_by(id=query_id, tenant_id=ctx.tenant_id).first()
    if not r:
        raise HTTPException(404, "Analysis not found.")
    snap = r.result_snapshot or {}
    pinned = bool(
        db.query(PinnedAnalysis)
        .filter_by(tenant_id=ctx.tenant_id, user_id=ctx.user_id, query_id=query_id)
        .first()
    )
    return {
        "final": True,
        "query_id": r.id,
        "pinned": pinned,
        "conversation_id": r.conversation_id,
        "resolved_question": r.question,
        "sql": snap.get("sql", r.generated_sql),
        # Older rows saved before sql_rationale/truncated were added to the
        # snapshot won't have them - default rather than KeyError.
        "sql_rationale": snap.get("sql_rationale", ""),
        "row_count": r.row_count,
        "duration_ms": r.duration_ms,
        "truncated": snap.get("truncated", False),
        "data_quality": snap.get("data_quality", {}),
        "metrics": snap.get("metrics", {}),
        "by_group": snap.get("by_group"),
        "anomalies": snap.get("anomalies", []),
        "investigation": snap.get("investigation", []),
        "forecast": snap.get("forecast", []),
        "documents_used": snap.get("documents_used", []),
        "insight": snap.get("insight", {"error": "Not available for this analysis."}),
        "preview_rows": snap.get("preview_rows", []),
    }


@router.get("/artifacts")
def list_artifacts(kind: str | None = None, limit: int = 50, db: Session = Depends(get_db),
                    ctx: AuthContext = Depends(get_current_user)):
    q = db.query(GeneratedArtifact).filter_by(tenant_id=ctx.tenant_id)
    if kind:
        q = q.filter_by(kind=kind)
    rows = q.order_by(GeneratedArtifact.created_at.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "title": a.title,
            "source_query_id": a.source_query_id,
            "url": f"/artifacts/{os.path.basename(a.file_path)}",
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]
