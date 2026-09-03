"""
Credential encryption for stored data-source connections.

Two backends, chosen by settings.kms_provider:

- "local" (default, dev): a single static Fernet key from
  settings.app_secret_key, held in this process's own environment. Simple,
  but the encryption key and the encrypted data end up in the same trust
  boundary - a metadata-DB leak plus that one env var is enough to decrypt
  every stored credential, since nothing about decrypting requires proving
  who you are beyond having that string.

- "aws" (production): envelope encryption via AWS KMS. Every credential
  gets its own randomly-generated 256-bit data key (via KMS's
  GenerateDataKey); only *that* data key - never the credential itself -
  is sent to KMS to be wrapped by a master key that never leaves AWS's
  HSMs. The stored token is the KMS-wrapped data key plus the
  Fernet-encrypted credential; decrypting requires an actual network call
  to KMS with IAM permission on that specific key, which CloudTrail logs.
  A metadata-DB leak alone is no longer sufficient to decrypt anything.
  See docs/CLOUD_KMS.md for setup - this backend is built strictly to
  AWS's documented KMS API and has NOT been exercised against a real AWS
  account in this environment (no credentials available); the encrypt/
  decrypt round-trip and request shape are verified against a mocked KMS
  client instead - see the module docstring's honesty norm elsewhere in
  this codebase (e.g. app/connectors/mssql.py, app/billing/paystack.py)
  for why that distinction matters and isn't glossed over here either.

Design goals unchanged from the original single-backend version (BUILD
SPEC section 8):
- Raw DB passwords are never stored in plaintext in the metadata DB.
- Decrypted credentials are only ever materialized in memory for the
  duration of a single connector call, never logged, never sent to the LLM,
  never returned to the frontend.
"""
import base64
from cryptography.fernet import Fernet
from app.config import settings


class _LocalBackend:
    """The original implementation - a single static Fernet key. Kept as
    the default so local dev and any deployment without AWS credentials
    configured keeps working exactly as before; nothing about this backend
    changed."""

    def __init__(self):
        self._fernet = Fernet(settings.app_secret_key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()


class _AwsKmsBackend:
    """Envelope encryption. The stored token format is
    "<base64 KMS-wrapped data key>.<Fernet ciphertext>" - "." is a safe
    delimiter because neither half's own base64 alphabet (urlsafe: A-Z,
    a-z, 0-9, "-", "_", "=") ever contains it. The plaintext data key
    KMS hands back only ever exists in memory for the duration of one
    encrypt/decrypt call - it is never logged, stored, or returned."""

    def __init__(self):
        import boto3  # imported lazily so "local" mode never requires it installed
        if not settings.aws_kms_key_id:
            raise RuntimeError("KMS_PROVIDER=aws requires AWS_KMS_KEY_ID to be set.")
        self._client = boto3.client("kms", region_name=settings.aws_region)
        self._key_id = settings.aws_kms_key_id

    def encrypt(self, value: str) -> str:
        response = self._client.generate_data_key(KeyId=self._key_id, KeySpec="AES_256")
        plaintext_key: bytes = response["Plaintext"]
        wrapped_key: bytes = response["CiphertextBlob"]
        data_fernet = Fernet(base64.urlsafe_b64encode(plaintext_key))
        ciphertext = data_fernet.encrypt(value.encode()).decode()
        return f"{base64.urlsafe_b64encode(wrapped_key).decode()}.{ciphertext}"

    def decrypt(self, token: str) -> str:
        wrapped_key_b64, ciphertext = token.split(".", 1)
        wrapped_key = base64.urlsafe_b64decode(wrapped_key_b64.encode())
        response = self._client.decrypt(CiphertextBlob=wrapped_key, KeyId=self._key_id)
        plaintext_key: bytes = response["Plaintext"]
        data_fernet = Fernet(base64.urlsafe_b64encode(plaintext_key))
        return data_fernet.decrypt(ciphertext.encode()).decode()


def _build_backend():
    if settings.kms_provider == "aws":
        return _AwsKmsBackend()
    return _LocalBackend()


_backend = _build_backend()


def encrypt(value: str) -> str:
    return _backend.encrypt(value)


def decrypt(token: str) -> str:
    return _backend.decrypt(token)


class RedactedSecret(str):
    """
    Wrapper so that if a decrypted credential is ever accidentally passed to
    logging, str(), or an f-string, it prints as REDACTED instead of the
    real value. Connectors unwrap it explicitly with `.reveal()` at the
    point of use only.
    """

    def __new__(cls, value: str):
        obj = str.__new__(cls, "***REDACTED***")
        obj._value = value
        return obj

    def reveal(self) -> str:
        return self._value

    def __repr__(self):
        return "RedactedSecret('***REDACTED***')"
