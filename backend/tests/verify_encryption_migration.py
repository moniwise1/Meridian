"""Real cipher/SQLite migration and exact stubbed KMS calls; no AWS account used."""
import os
import tempfile
from pathlib import Path
os.environ["APP_SECRET_KEY"] = "dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA="
os.environ["METADATA_DB_URL"] = "sqlite:///" + str(Path(tempfile.mkdtemp()) / "migration.db")
os.environ["AWS_ACCESS_KEY_ID"] = "test-only"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test-only"
from unittest.mock import patch
from botocore.stub import Stubber
from app.config import settings
from app.security import secrets
from app.db.session import init_db, SessionLocal
from app.db.models import DataSourceConnection, User, Tenant, StoredFile
from scripts.migrate_encryption import migrate

settings.aws_kms_key_id = "arn:aws:kms:us-east-1:111122223333:key/12345678-1234-1234-1234-123456789012"
local = secrets._LocalBackend()
aws = secrets._AwsKmsBackend()
wrapped = b"wrapped-key-test"
plain_key = b"k" * 32
with Stubber(aws._client) as stub:
    stub.add_response("generate_data_key", {"Plaintext":plain_key, "CiphertextBlob":wrapped, "KeyId":settings.aws_kms_key_id},
                      {"KeyId":settings.aws_kms_key_id,"KeySpec":"AES_256"})
    encrypted = aws.encrypt("private-synthetic-value")
    assert "private-synthetic-value" not in encrypted and "." in encrypted
    stub.add_response("decrypt", {"Plaintext":plain_key,"KeyId":settings.aws_kms_key_id},
                      {"CiphertextBlob":wrapped,"KeyId":settings.aws_kms_key_id})
    assert aws.decrypt(encrypted) == "private-synthetic-value"
    stub.add_response("decrypt", {"Plaintext":plain_key,"KeyId":settings.aws_kms_key_id},
                      {"CiphertextBlob":wrapped,"KeyId":settings.aws_kms_key_id})
    with patch.object(secrets, "_backend", local), patch.object(secrets, "_kms_decryption_backend", return_value=aws):
        assert secrets.decrypt(encrypted) == "private-synthetic-value"
    stub.assert_no_pending_responses()
with patch.object(secrets, "_backend", aws):
    assert secrets.decrypt(local.encrypt("legacy")) == "legacy"

init_db(); db = SessionLocal()
db.add(Tenant(id="t", name="Migration test"))
db.add(User(id="u", tenant_id="t", email="migration@example.com", password_hash="unused", totp_secret=local.encrypt("SYNTHETIC-TOTP")))
db.add(DataSourceConnection(id="c", tenant_id="t", name="Synthetic", kind="postgres", host="example.invalid", port=5432,
    database="synthetic", username="reader", encrypted_password=local.encrypt("synthetic-password")))
cipher = local.encrypt("synthetic-file-base64").encode()
db.add(StoredFile(id="document:d", tenant_id="t", kind="document", object_id="d", sha256="synthetic", size_bytes=len(cipher), ciphertext=cipher))
db.commit()
baseline = migrate(db)
assert sum(v["legacy"] for v in baseline.values()) == 3
assert all(v["migrated"] == 0 for v in baseline.values())
class Target:
    def encrypt(self, value): return "test-envelope." + local.encrypt(value)
    def decrypt(self, value): return local.decrypt(value.split(".",1)[1])
result = migrate(db, apply=True, local=local, target=Target(), batch_size=1)
assert sum(v["migrated"] for v in result.values()) == 3
assert all(v["legacy"] == 0 for v in migrate(db).values())
row = db.query(StoredFile).one()
assert row.size_bytes == len(row.ciphertext)
# An invalid target roundtrip leaves the active batch unchanged.
user = db.query(User).one(); user.totp_secret = local.encrypt("another-synthetic-secret"); db.commit()
original = user.totp_secret
class InvalidTarget(Target):
    def decrypt(self, value): return "wrong"
try: migrate(db, apply=True, local=local, target=InvalidTarget())
except RuntimeError: pass
else: raise AssertionError("Invalid roundtrip accepted")
db.expire_all()
assert db.query(User).one().totp_secret == original
print("Mixed-format reads, exact KMS contract, dry run, all secret classes, idempotency and batch rollback passed")
