"""Operator-only synthetic recovery test. Run in the backend container.

create -> restart backend -> verify -> cleanup. No customer records, passwords,
model calls, billing requests, emails, or public credentials are used.
"""
import argparse
import hashlib
import os
import re
import uuid
from pathlib import Path
import httpx
from sqlalchemy import delete
from app.config import settings
from app.db.models import Base, Tenant, User, UploadedDocument, QueryRecord, GeneratedArtifact, StoredFile
from app.db.session import SessionLocal
from app.security.auth import create_access_token
from app.api.routes_artifacts import artifact_download_url
from app.file_storage import ensure_file

NAME = "Meridian storage recovery probe"
CONTENT = b"Team,Wait\nSupport,20\nRetail,5\n"


def checked_probe(db, tenant_id):
    if not re.fullmatch(r"recovery-probe-[a-f0-9]{32}", tenant_id):
        raise RuntimeError("Not a recovery-probe identifier")
    tenant = db.query(Tenant).filter_by(id=tenant_id, name=NAME).first()
    user = db.query(User).filter_by(tenant_id=tenant_id, email=tenant_id + "@example.invalid").first()
    if not tenant or not user or user.password_hash != "disabled-recovery-probe":
        raise RuntimeError("Recovery-probe identity check failed")
    return tenant, user


def run(db, phase, tenant_id=None):
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise RuntimeError("Invalid backend port")
    origin = f"http://127.0.0.1:{port}"
    if phase == "create":
        tenant_id = "recovery-probe-" + uuid.uuid4().hex
        tenant = Tenant(id=tenant_id, name=NAME, account_type="individual",
                        plan="individual_basic", subscription_status="active")
        user = User(tenant_id=tenant_id, email=tenant_id + "@example.invalid", role="admin",
                    password_hash="disabled-recovery-probe", marketing_opt_in=False)
        db.add_all([tenant, user]); db.commit()
        print({"probe_created":tenant_id})  # retained for cleanup even if a later step fails
    tenant, user = checked_probe(db, tenant_id)
    if phase == "cleanup":
        paths = [d.file_path for d in db.query(UploadedDocument).filter_by(tenant_id=tenant_id)]
        paths += [a.file_path for a in db.query(GeneratedArtifact).filter_by(tenant_id=tenant_id)]
        for filename in paths:
            path = Path(filename)
            if any(path.resolve().is_relative_to(Path(root).resolve()) for root in [settings.documents_dir, settings.artifacts_dir]):
                path.unlink(missing_ok=True)
        for table in reversed(Base.metadata.sorted_tables):
            if "tenant_id" in table.c:
                db.execute(delete(table).where(table.c.tenant_id == tenant_id))
        db.execute(delete(Tenant).where(Tenant.id == tenant_id)); db.commit()
        return {"probe_id":tenant_id, "cleanup":"complete"}
    headers = {"Authorization":"Bearer " + create_access_token(user.id, tenant_id, user.role)}
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        if phase == "create":
            response = client.post(origin + "/documents/upload", headers=headers,
                files={"file":("synthetic-recovery.csv",CONTENT,"text/csv")}, timeout=30)
            if response.status_code != 200:
                raise RuntimeError("Synthetic upload failed")
            document_id = response.json()["id"]
            record = QueryRecord(id="AQ-" + uuid.uuid4().hex, tenant_id=tenant_id, user_id=user.id,
                connection_id="document-only", question="Synthetic storage recovery test",
                generated_sql="-- Synthetic document fixture, no SQL executed", row_count=2, duration_ms=0,
                result_snapshot={"source_document_ids":[document_id], "metrics":{"total":25,"mean":12.5},
                    "insight":{"what":"Synthetic fixture: two rows, total wait 25 minutes.","confidence":"high",
                        "confidence_explanation":"Known synthetic fixture.","data_quality_caveat":"Not customer data."},
                    "by_group":[{"group":"Support","total":20},{"group":"Retail","total":5}],
                    "data_quality":{"row_count":2,"notes":["Synthetic recovery test"]}})
            db.add(record); db.commit()
            response = client.post(origin + "/artifacts/report/" + record.id, headers=headers, timeout=60)
            if response.status_code != 200:
                raise RuntimeError("Synthetic report generation failed")
            artifact_id = response.json()["id"]
            record.result_snapshot = {**record.result_snapshot, "recovery_probe":{"artifact_id":artifact_id}}
            db.commit()
        record = db.query(QueryRecord).filter_by(tenant_id=tenant_id, user_id=user.id).one()
        document = db.query(UploadedDocument).filter_by(id=record.result_snapshot["source_document_ids"][0], tenant_id=tenant_id).one()
        artifact = db.query(GeneratedArtifact).filter_by(id=record.result_snapshot["recovery_probe"]["artifact_id"], tenant_id=tenant_id).one()
        if db.query(StoredFile).filter_by(tenant_id=tenant_id).count() != 2:
            raise RuntimeError("Durable document/report records missing")
        missing_before_restore = not Path(document.file_path).is_file() and not Path(artifact.file_path).is_file()
        if not ensure_file(db, tenant_id, "document", document.id, document.file_path):
            raise RuntimeError("Synthetic document restore failed")
        if Path(document.file_path).read_bytes() != CONTENT:
            raise RuntimeError("Synthetic document bytes differ")
        response = client.get(origin + artifact_download_url(artifact), timeout=30)
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            raise RuntimeError("Signed PDF restore failed")
        expected_pdf = record.result_snapshot.get("recovery_pdf_sha256")
        actual_pdf = hashlib.sha256(response.content).hexdigest()
        if phase == "create":
            record.result_snapshot = {**record.result_snapshot,"recovery_pdf_sha256":actual_pdf}
            db.commit()
        elif expected_pdf != actual_pdf:
            raise RuntimeError("Synthetic PDF bytes differ")
        return {"probe_id":tenant_id,"phase":phase,"durable_objects":2,
                "original_bytes_match":True,"both_caches_missing_before_restore":missing_before_restore}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["create","verify","cleanup"])
    parser.add_argument("--probe-id")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        print(run(db, args.phase, args.probe_id))
    except Exception:
        db.rollback()
        print("Recovery probe stopped. Inspect securely; no credentials or raw errors are printed.")
        raise SystemExit(1)
    finally:
        db.close()
