"""
Throwaway verification for security fix #3 - validate_startup_config must
hard-fail a production / real-KMS deployment with collapsed secrets.
Run from backend/:  PYTHONPATH=$(pwd) python <this file>
"""
import base64, os
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())

from types import SimpleNamespace
from app.config import validate_startup_config, StartupConfigError


def cfg(**over):
    base = dict(
        environment="development", app_secret_key="AAA", jwt_secret_key="", platform_jwt_secret="",
        kms_provider="local", aws_kms_key_id="",
        metadata_db_url="sqlite:///./metadata.db", frontend_origin="http://localhost:3000",
    )
    base.update(over)
    return SimpleNamespace(**base)


# 1. development + fully collapsed secrets -> allowed, no warnings, no raise
assert validate_startup_config(cfg()) == []
print("1. OK  development mode bypasses the checks entirely")

# 2. production + all three secrets identical -> raises, names all three problems
try:
    validate_startup_config(cfg(environment="production"))
    assert False, "should have raised"
except StartupConfigError as e:
    m = str(e)
    assert "JWT_SECRET_KEY" in m and "PLATFORM_JWT_SECRET" in m and "KMS_PROVIDER" in m, m
print("2. OK  production + collapsed secrets -> StartupConfigError listing all three")

# 3. KMS_PROVIDER=aws alone (environment still 'development') is also hardened
try:
    validate_startup_config(cfg(kms_provider="aws"))
    assert False, "should have raised"
except StartupConfigError:
    pass
print("3. OK  KMS_PROVIDER=aws alone triggers the hardened checks")

# 4. production + jwt set but == app_secret_key -> still an error
try:
    validate_startup_config(cfg(environment="production", jwt_secret_key="AAA",
                                platform_jwt_secret="BBB", kms_provider="aws", aws_kms_key_id="k"))
    assert False
except StartupConfigError as e:
    assert "JWT_SECRET_KEY" in str(e) and "PLATFORM_JWT_SECRET" not in str(e), str(e)
print("4. OK  jwt_secret_key == app_secret_key is rejected; a distinct platform secret passes")

# 5. production + platform secret == jwt secret -> rejected
try:
    validate_startup_config(cfg(environment="production", jwt_secret_key="BBB",
                                platform_jwt_secret="BBB", kms_provider="aws", aws_kms_key_id="k"))
    assert False
except StartupConfigError as e:
    assert "PLATFORM_JWT_SECRET" in str(e), str(e)
print("5. OK  platform_jwt_secret == jwt_secret_key is rejected")

# 6. aws but no key id -> rejected
try:
    validate_startup_config(cfg(environment="production", jwt_secret_key="BBB",
                                platform_jwt_secret="CCC", kms_provider="aws", aws_kms_key_id=""))
    assert False
except StartupConfigError as e:
    assert "AWS_KMS_KEY_ID" in str(e), str(e)
print("6. OK  KMS_PROVIDER=aws with no AWS_KMS_KEY_ID is rejected")

# 7. fully correct hardened config -> passes, returns only soft warnings
w = validate_startup_config(cfg(environment="production", jwt_secret_key="BBB",
                                platform_jwt_secret="CCC", kms_provider="aws", aws_kms_key_id="k",
                                metadata_db_url="sqlite:///x", frontend_origin="http://localhost:3000"))
assert any("SQLite" in x for x in w) and any("localhost" in x for x in w), w
w2 = validate_startup_config(cfg(environment="production", jwt_secret_key="BBB",
                                 platform_jwt_secret="CCC", kms_provider="aws", aws_kms_key_id="k",
                                 metadata_db_url="postgresql://h/d",
                                 frontend_origin="https://app.getmeridiananalytics.com"))
assert w2 == [], w2
print("7. OK  correct hardened config passes; SQLite / localhost come back as non-fatal warnings")

# 8. the real running app still boots in dev (import + startup event)
import base64 as _b
os.environ["METADATA_DB_URL"] = "sqlite:///" + os.path.join(os.environ.get("TMP", "/tmp"), "meta_startup_test.db")
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    assert c.get("/health").json() == {"status": "ok"}
print("8. OK  the real app still boots and serves /health in development mode")

print("\nALL CHECKS PASSED")
