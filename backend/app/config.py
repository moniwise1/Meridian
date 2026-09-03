"""
Central configuration. All security-relevant defaults live here so they are
easy to audit in one place, instead of scattered magic numbers through the app.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret_key: str
    metadata_db_url: str = "sqlite:///./metadata.db"
    anthropic_api_key: str = ""
    frontend_origin: str = "http://localhost:3000"

    default_row_limit: int = 1000
    max_row_limit: int = 20000
    query_timeout_seconds: int = 15
    artifacts_dir: str = "./artifacts"
    documents_dir: str = "./documents"
    max_document_upload_bytes: int = 20 * 1024 * 1024  # 20 MB

    # See app/security/rate_limit.py for what these bound and their
    # in-process (not cross-worker) limitation.
    ask_rate_limit_per_user_per_minute: int = 10
    ask_max_concurrent_per_tenant: int = 3

    # See app/agents/query_cache.py — only applies to fresh (non-follow-up)
    # questions; bounds how stale a cached answer can be.
    ask_cache_ttl_seconds: int = 300

    # Fast, cheap model for schema summarization / SQL generation.
    # Reserve a stronger model only for the final insight explanation step (see agents/insight_agent.py).
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_model_reasoning: str = "claude-sonnet-4-6"

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
