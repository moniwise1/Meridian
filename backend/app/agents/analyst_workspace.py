"""User-scoped analyst memory and durable, bounded upload checks."""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy import or_
from app.db.models import AskMemory, AskFinding, AskScanJob, UploadedDocument, User
from app.agents import tabular_analysis

log = logging.getLogger(__name__)


def policy_signature(connection, row_scope):
    return hashlib.sha256(json.dumps({"allowlist": connection.table_allowlist,
        "columns": connection.column_policy, "rows": row_scope}, sort_keys=True).encode()).hexdigest()


def memories_for(db, tenant_id, user_id, source_key):
    rows = db.query(AskMemory).filter_by(tenant_id=tenant_id, user_id=user_id, source_key=source_key).order_by(AskMemory.created_at.desc()).limit(30).all()
    return [{"id": r.id, "kind": r.kind, "content": r.content, "confirmed": True} for r in rows]


def enqueue_upload_check(db, doc):
    existing = db.query(AskScanJob).filter_by(document_id=doc.id).first()
    if not existing:
        db.add(AskScanJob(document_id=doc.id, tenant_id=doc.tenant_id, user_id=doc.user_id))


def scan_findings(doc):
    """No paid model calls. No invented causes or full-month comparisons."""
    tables, diagnostics = tabular_analysis.extract_tables(doc.file_path, doc.kind)
    table = tabular_analysis.pick_best_table(tables)
    if table is None:
        return [{"kind": "coverage", "title": "Numeric checks need a structured table", "detail":
                 "This upload could not be checked as a numeric table. " + "; ".join(diagnostics[:2]), "confidence": "not_assessable"}]
    profile = tabular_analysis.build_profile(table, "")
    quality, anomalies = tabular_analysis.compute_data_quality_and_anomalies(table, profile)
    findings = []
    if quality.completeness_pct < 95:
        findings.append({"kind": "quality", "title": "Missing values need review", "detail":
                         f"{quality.completeness_pct:.1f}% of cells are populated in the selected table. Missing values are not zero.", "confidence": "high"})
    if quality.duplicate_pct > 0:
        findings.append({"kind": "quality", "title": "Repeated rows detected", "detail":
                         f"{quality.duplicate_pct:.1f}% of rows repeat an earlier row. Confirm whether these are legitimate before aggregating.", "confidence": "high"})
    for anomaly in anomalies[:3]:
        findings.append({"kind": "anomaly", "title": anomaly.what, "detail":
                         f"{anomaly.magnitude}. {anomaly.evidence} Reporting-period completeness and seasonality have not been verified; this is a review signal, not a confirmed cause.", "confidence": "medium"})
    return findings[:3]


def run_pending_checks(tenant_id: str, user_id: str):
    # Own short-lived session: request sessions must never escape into a background task.
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id, tenant_id=tenant_id).first()
        if not user or "document_retrieval" not in (user.capabilities or []):
            return
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        jobs = db.query(AskScanJob).filter_by(tenant_id=tenant_id, user_id=user_id).filter(
            AskScanJob.attempts < 3,
            or_(AskScanJob.status.in_(["pending", "failed"]),
                (AskScanJob.status == "running") & (AskScanJob.updated_at < cutoff)),
        ).order_by(AskScanJob.created_at).limit(3).all()
        for job in jobs:
            # Optimistic claim prevents simultaneous page/upload requests doing duplicate work.
            claimed = db.query(AskScanJob).filter_by(id=job.id, status=job.status, attempts=job.attempts).update(
                {"status": "running", "attempts": job.attempts + 1, "updated_at": datetime.utcnow()}, synchronize_session=False)
            db.commit()
            if not claimed:
                continue
            try:
                doc = db.query(UploadedDocument).filter_by(id=job.document_id, tenant_id=tenant_id).first()
                if doc:
                    for item in scan_findings(doc):
                        key = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                        fid = hashlib.sha256(f"{tenant_id}:{user_id}:{doc.id}:{key}".encode()).hexdigest()
                        if not db.query(AskFinding).filter_by(id=fid).first():
                            db.add(AskFinding(id=fid, tenant_id=tenant_id, user_id=user_id,
                                document_id=doc.id, source_version=getattr(doc, "content_sha256", None),
                                payload=item, status="new"))
                db.query(AskScanJob).filter_by(id=job.id).update({"status": "complete", "updated_at": datetime.utcnow()}, synchronize_session=False)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("Upload check failed for job %s", job.id)
                db.query(AskScanJob).filter_by(id=job.id).update({"status": "failed", "updated_at": datetime.utcnow()}, synchronize_session=False)
                db.commit()
    finally:
        db.close()
