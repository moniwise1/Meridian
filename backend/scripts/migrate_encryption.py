"""Staged local-to-KMS migration. Dry run by default; never prints secret values.

Provision and test a restricted KMS key, deploy dual-format reads first, and
take a restorable backup. Run with existing APP_SECRET_KEY and scoped AWS
credentials. Leave the old key available until legacy count is zero.
"""
import argparse
from sqlalchemy import func, text
from app.config import settings
from app.db.models import DataSourceConnection, User, StoredFile
from app.db.session import SessionLocal
from app.security.secrets import _LocalBackend, _AwsKmsBackend

FIELDS = [(DataSourceConnection, "encrypted_password"), (User, "totp_secret"), (StoredFile, "ciphertext")]


def migrate(db, *, apply=False, batch_size=10, local=None, target=None):
    if not 1 <= batch_size <= 100:
        raise ValueError("Batch size must be between 1 and 100")
    counts = {}
    for model, field in FIELDS:
        cursor = ""
        legacy = migrated = 0
        while True:
            query = db.query(model).filter(model.id > cursor, getattr(model, field).is_not(None)).order_by(model.id).limit(batch_size)
            if apply:
                query = query.with_for_update()
            rows = query.all()
            if not rows:
                break
            changed = 0
            try:
                for row in rows:
                    cursor = row.id
                    original = getattr(row, field)
                    token = original.decode("ascii") if isinstance(original, bytes) else original
                    if "." in token:
                        continue
                    legacy += 1
                    if not apply:
                        continue
                    plaintext = local.decrypt(token)
                    replacement = target.encrypt(plaintext)
                    if target.decrypt(replacement) != plaintext:
                        raise RuntimeError("KMS roundtrip validation failed")
                    if model is StoredFile:
                        if db.bind.dialect.name == "postgresql":
                            db.execute(text("SELECT pg_advisory_xact_lock(723401927)"))
                        replacement = replacement.encode("ascii")
                        delta = len(replacement) - row.size_bytes
                        total = db.query(func.coalesce(func.sum(StoredFile.size_bytes), 0)).scalar()
                        tenant = db.query(func.coalesce(func.sum(StoredFile.size_bytes), 0)).filter_by(tenant_id=row.tenant_id).scalar()
                        if total + delta > settings.max_stored_files_bytes or tenant + delta > settings.max_tenant_stored_files_bytes:
                            raise RuntimeError("Migration would exceed the durable storage budget")
                        row.size_bytes = len(replacement)
                    setattr(row, field, replacement)
                    db.flush()
                    changed += 1
                if apply:
                    db.commit()
                    migrated += changed
            except Exception:
                db.rollback()
                raise
        counts[model.__tablename__] = {"legacy": legacy, "migrated": migrated}
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = migrate(db, apply=args.apply, batch_size=args.batch_size,
                         local=_LocalBackend() if args.apply else None,
                         target=_AwsKmsBackend() if args.apply else None)
        print(result)
    except Exception:
        # SDK/DB errors may contain non-public metadata; log no raw error text.
        print("Migration stopped. The active batch was rolled back. Investigate securely before retrying.")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
