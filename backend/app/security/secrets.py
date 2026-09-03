"""
Credential encryption for stored data-source connections.

Design goals (see BUILD SPEC section 8):
- Raw DB passwords are never stored in plaintext in the metadata DB.
- Decrypted credentials are only ever materialized in memory for the
  duration of a single connector call, never logged, never sent to the LLM,
  never returned to the frontend.
"""
from cryptography.fernet import Fernet
from app.config import settings

_fernet = Fernet(settings.app_secret_key.encode())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


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
