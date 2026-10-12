"""Encrypted file durability on the metadata DB; local files are just caches.

Callers must authorize the document/artifact BEFORE calling this module.
No external provider or public download path is introduced.
"""
import base64
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, text
from app.config import settings
from app.db.models import StoredFile
from app.security.secrets import encrypt, decrypt


def _key(kind, object_id):
    if kind not in {"document", "artifact"}:
        raise ValueError("Unsupported storage object")
    return kind + ":" + object_id


def store_bytes(db, tenant_id, kind, object_id, content):
    if len(content) > settings.max_stored_file_bytes:
        raise HTTPException(413, "This file exceeds the durable storage size limit.")
    key = _key(kind, object_id)
    existing = db.query(StoredFile).filter_by(id=key).first()
    digest = hashlib.sha256(content).hexdigest()
    if existing:
        if existing.tenant_id != tenant_id or existing.sha256 != digest:
            raise RuntimeError("Storage object identity mismatch")
        return
    encrypted = encrypt(base64.b64encode(content).decode("ascii")).encode("ascii")
    # Serialize quota checks across backend replicas on production Postgres.
    # SQLite is for development/testing, not a production storage deployment.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(723401927)"))
        existing = db.query(StoredFile).filter_by(id=key).first()
        if existing:
            if existing.tenant_id != tenant_id or existing.sha256 != digest:
                raise RuntimeError("Storage object identity mismatch")
            return
    db.flush()
    used = db.query(func.coalesce(func.sum(StoredFile.size_bytes), 0)).scalar()
    tenant_used = db.query(func.coalesce(func.sum(StoredFile.size_bytes), 0)).filter_by(tenant_id=tenant_id).scalar()
    if used + len(encrypted) > settings.max_stored_files_bytes or tenant_used + len(encrypted) > settings.max_tenant_stored_files_bytes:
        raise HTTPException(413, "Durable file storage is full. Contact support before uploading or generating more files.")
    db.add(StoredFile(id=key, tenant_id=tenant_id, kind=kind, object_id=object_id,
                      sha256=digest, size_bytes=len(encrypted), ciphertext=encrypted))
    db.flush()


def store_path(db, tenant_id, kind, object_id, path):
    with open(path, "rb") as stream:
        content = stream.read(settings.max_stored_file_bytes + 1)
    store_bytes(db, tenant_id, kind, object_id, content)


def ensure_file(db, tenant_id, kind, object_id, path):
    """Backfill available legacy bytes or restore a missing local cache.

    Returns False for missing legacy originals. Extracted text cannot recover
    the original upload, and this function never pretends otherwise.
    """
    row = db.query(StoredFile).filter_by(id=_key(kind, object_id)).first()
    if row is not None and row.tenant_id != tenant_id:
        return False
    target = Path(path)
    if target.is_file():
        if row is None:
            store_path(db, tenant_id, kind, object_id, path)
            db.commit()  # finish durability before a model/connector call
            return True
        with target.open("rb") as stream:
            local = stream.read(settings.max_stored_file_bytes + 1)
        if hashlib.sha256(local).hexdigest() == row.sha256:
            return True
    if row is None:
        return False
    root = Path(settings.documents_dir if kind == "document" else settings.artifacts_dir).resolve()
    if not target.resolve().is_relative_to(root):
        raise RuntimeError("Storage cache path is outside the configured directory")
    content = base64.b64decode(decrypt(row.ciphertext.decode("ascii")), validate=True)
    if len(content) > settings.max_stored_file_bytes or hashlib.sha256(content).hexdigest() != row.sha256:
        raise RuntimeError("Stored file integrity check failed")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".restore-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def delete_bytes(db, tenant_id, kind, object_id):
    db.query(StoredFile).filter_by(id=_key(kind, object_id), tenant_id=tenant_id).delete()
