"""
Central configuration. All security-relevant defaults live here so they are
easy to audit in one place, instead of scattered magic numbers through the app.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret_key: str
    # Falls back to app_secret_key if unset, matching the original
    # single-key behavior - see the note in app/security/auth.py on why
    # splitting this from the credential-encryption key matters.
    jwt_secret_key: str = ""
    # Signs platform-staff (internal admin) sessions - see
    # app/security/platform_auth.py for why this is deliberately a THIRD
    # secret, separate from both app_secret_key and jwt_secret_key. Falls
    # back to jwt_secret_key, then app_secret_key, if unset.
    platform_jwt_secret: str = ""
    metadata_db_url: str = "sqlite:///./metadata.db"
    anthropic_api_key: str = ""
    frontend_origin: str = "http://localhost:3000"

    # Credential encryption backend - see app/security/secrets.py.
    # "local" (default): a static Fernet key from app_secret_key, fine for
    # dev. "aws": envelope encryption via AWS KMS for production - see
    # docs/CLOUD_KMS.md.
    kms_provider: str = "local"
    aws_kms_key_id: str = ""
    aws_region: str = "us-east-1"

    default_row_limit: int = 1000
    max_row_limit: int = 20000
    query_timeout_seconds: int = 15
    artifacts_dir: str = "./artifacts"
    documents_dir: str = "./documents"
    max_document_upload_bytes: int = 20 * 1024 * 1024  # 20 MB

    # Shared backing store for rate_limit.py / login_cooldown.py /
    # query_cache.py. Empty (default): each falls back to in-process
    # memory, correct for a single instance, silently weaker behind
    # multiple workers/replicas (see each module's own docstring). Set to
    # a real Redis URL (redis://... or rediss://... for TLS) to make all
    # three genuinely global across every instance - the same fix for all
    # three, since they're the same category of gap.
    redis_url: str = ""

    # See app/security/rate_limit.py for what these bound and their
    # in-process (not cross-worker) limitation when redis_url is unset.
    ask_rate_limit_per_user_per_minute: int = 10
    ask_max_concurrent_per_tenant: int = 3

    # See app/agents/query_cache.py — only applies to fresh (non-follow-up)
    # questions; bounds how stale a cached answer can be.
    ask_cache_ttl_seconds: int = 300

    # See app/security/login_cooldown.py. Deliberately generous: failures
    # up to this count cost nothing (typos/autofill are normal), and the
    # backoff after that is capped so a genuine user is only ever slowed
    # down, never permanently locked out - a hard lockout on a paid
    # account is a support ticket and a churn risk, not just a UX papercut.
    login_free_attempts: int = 5
    login_cooldown_base_seconds: float = 15.0
    login_cooldown_max_seconds: float = 900.0  # 15 minutes
    # Failure history for a key is forgotten after this long of no further
    # failures, so one bad evening months ago never lingers.
    login_cooldown_reset_after_seconds: float = 1800.0  # 30 minutes

    # Fast, cheap model for schema summarization / SQL generation.
    # Reserve a stronger model only for the final insight explanation step (see agents/insight_agent.py).
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_model_reasoning: str = "claude-sonnet-5"

    # Billing (app/billing/paystack.py, app/api/routes_billing.py). Paid-
    # from-onset model: a tenant is charged immediately on subscribe, with a
    # self-serve full refund if they cancel within billing_refund_window_days.
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    paystack_plan_code: str = ""
    # Smallest currency unit (kobo for NGN, cents for USD, pesewas for GHS,
    # ...) - must match the plan's real price. Passed explicitly on every
    # initialize call rather than relying on Paystack's documented (but
    # unverified here - no live account to test against) behavior of
    # inferring the amount from the plan code alone.
    paystack_plan_amount: int = 0
    billing_refund_window_days: int = 7

    class Config:
        env_file = ".env"


settings = Settings()
