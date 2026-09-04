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
    # Comma-separated when there's more than one real frontend origin to
    # allow (e.g. a custom domain plus the platform's own auto-generated
    # *.up.railway.app URL, kept reachable as a fallback/testing path) -
    # a single value works exactly as before, unchanged for every existing
    # deployment. See frontend_origins below for the parsed form
    # CORSMiddleware actually uses.
    frontend_origin: str = "http://localhost:3000"

    # The bare domain per-tenant subdomains hang off (wamco.<this>) - used
    # to build links that must land on a SPECIFIC tenant's subdomain
    # (invite-accept emails, see app/invites.py) from the backend, which
    # has no request Origin to read one back from the way the frontend's
    # own NEXT_PUBLIC_APEX_DOMAIN does. Matches that frontend default -
    # keep the two in sync if this ever changes.
    apex_domain: str = "getmeridiananalytics.com"

    @property
    def frontend_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

    # frontend_origins above is a fixed, enumerable list - fine for "the
    # marketing domain plus a fallback URL", structurally wrong for
    # per-tenant subdomains (app/tenant_slug.py), which are created
    # dynamically and can never all be individually enumerated here. This
    # is a regex tested against the request's Origin header instead
    # (FastAPI's CORSMiddleware allow_origin_regex, OR'd together with the
    # exact-match list above - either one matching is enough). Empty
    # (default) disables subdomain CORS entirely without touching the
    # fixed list's own behavior. Example:
    # FRONTEND_ORIGIN_REGEX=https://([a-z0-9-]+\.)?getmeridiananalytics\.com
    frontend_origin_regex: str = ""

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
    # Override for pytesseract's path to the Tesseract binary - needed
    # only where it isn't already resolvable on PATH (e.g. local Windows
    # dev, if its installer didn't add itself to PATH for an already-open
    # shell). Leave unset in Docker/Linux production - apt-installed
    # tesseract-ocr is already on PATH there, no override needed. See
    # app/agents/document_intelligence.py's OCR fallback.
    tesseract_cmd: str = ""

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

    # Billing (app/billing/paystack.py, app/billing/plans.py,
    # app/api/routes_billing.py). Paid-from-onset model: a tenant is
    # charged immediately on subscribe, with a self-serve full refund if
    # they cancel within billing_refund_window_days.
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    billing_refund_window_days: int = 7

    # Three plans (Basic/Pro/Premium), each its own real Paystack Plan
    # object - not one plan reused at different prices, since Paystack's
    # own model is "a plan has one price". Amount is the smallest currency
    # unit (kobo for NGN) - must match the real price configured on each
    # Paystack plan exactly; passed explicitly on every initialize call
    # rather than relying on Paystack's documented (but unverified here -
    # no live account to test against) behavior of inferring the amount
    # from the plan code alone. See app/billing/plans.py for where these
    # combine with each plan's seat limit and feature copy.
    paystack_plan_code_basic: str = ""
    paystack_plan_amount_basic: int = 500_000  # NGN 5,000
    paystack_plan_code_pro: str = ""
    paystack_plan_amount_pro: int = 999_900  # NGN 9,999
    paystack_plan_code_premium: str = ""
    paystack_plan_amount_premium: int = 2_500_000  # NGN 25,000

    # Email delivery (app/agents/email_delivery.py). "console" (default):
    # logs instead of sending - the original MVP stand-in, still what a
    # fresh dev environment gets with zero config. "smtp": a real generic
    # SMTP backend - deliberately provider-agnostic (stdlib smtplib, no
    # vendor SDK) rather than committing to one specific provider's API,
    # so it works with anything that speaks SMTP: Gmail (an app password),
    # Postmark/SendGrid/SES's SMTP relays, or a domain's own mail hosting.
    email_provider: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # What recipients see in the "From" field - falls back to
    # smtp_username (the common case: they're the same address) if unset,
    # since some providers' SMTP auth username IS the send-as address and
    # requiring it twice would be redundant.
    smtp_from_address: str = ""
    smtp_use_tls: bool = True  # STARTTLS - true for every mainstream provider's port 587

    # Externally-anchored audit checkpoints (app/audit/anchor.py). The
    # hash chain in app/audit/logger.py is tamper-EVIDENT, not tamper-
    # PROOF, precisely because the hashes live in the same DB they protect
    # - this is the "anchor the chain's head hash somewhere outside this
    # database entirely" fix that module's own docstring calls out as not
    # implemented. Anchor target is a GitHub repo (any repo - doesn't have
    # to be this one), appended to via GitHub's Contents API using a
    # fine-grained personal access token scoped to just that repo's
    # Contents: Read and write permission. Unset (default) disables the
    # feature entirely - checkpoint publishing is admin-triggered
    # (POST /platform/audit/checkpoint), not automatic, since this app has
    # no background job scheduler; pair it with an external cron (a
    # scheduled GitHub Action, a Railway cron service, anything that can
    # hit an HTTP endpoint on a schedule) for genuinely periodic anchoring.
    audit_anchor_github_token: str = ""
    audit_anchor_github_repo: str = ""  # "owner/repo"
    audit_anchor_github_path: str = "audit_checkpoints.jsonl"
    # A dedicated branch, deliberately NOT main - checkpoint commits are
    # unrelated to code history, and a repo with PR-required branch
    # protection on main (enforce_admins included) will flatly reject a
    # direct Contents API write there regardless of token permissions -
    # caught for real against this exact repo during development, not
    # theorized about (see app/audit/anchor.py's module docstring).
    # Created automatically from main's current tip on first publish if
    # it doesn't exist yet.
    audit_anchor_github_branch: str = "audit-checkpoints"

    class Config:
        env_file = ".env"


settings = Settings()
