"""
The three paid plans (Basic/Pro/Premium) - single source of truth for
price, seat limit, data-source-connection limit, and the feature copy
shown on each pricing card, so the API response, the enforcement checks
in routes_auth.py/routes_connections.py, and the frontend cards can never
quietly drift apart from each other the way three separately-maintained
copies of "the plans" would.

Deliberately honest about what differentiates the tiers: every paid plan
gets the same PRODUCT capabilities (Ask, Risk scan, document intelligence,
row/column access control, the full audit trail) - there's no fake
feature-gating invented here just to make three cards look different.
What genuinely differs is seats, data-source connections, and now
monthly usage (questions asked, documents generated - see the *_limit
fields below and their use in routes_auth.py's invite_teammate /
routes_connections.py's create_connection / routes_ask.py's ask_stream /
routes_artifacts.py's create_report|create_presentation|create_export),
plus price. A card's "features" list states this plainly rather than
implying Basic gets a worse product.

Free (no paid plan) isn't in PLANS at all - it's the tenant's default
state (Tenant.tier == "free"), already gated out of the core paid actions
entirely by require_active_subscription (app/security/auth.py), with its
own 1-seat cap already enforced in routes_auth.py before this module
existed.
"""
from dataclasses import dataclass

from app.config import settings


@dataclass
class Plan:
    key: str  # "basic" | "pro" | "premium" - stored on Tenant.plan once subscribed
    label: str
    amount: int  # smallest currency unit (kobo for NGN)
    paystack_plan_code: str
    seat_limit: int | None  # None = unlimited
    connection_limit: int | None  # None = unlimited
    # Calendar-month usage caps (see app/billing/usage.py for how "this
    # month" is counted) - None = unlimited. query_limit counts questions
    # asked (routes_ask.py's ask_stream); document_limit counts every
    # report/presentation/export GENERATED (routes_artifacts.py) - not
    # each time an already-generated file is re-downloaded, since
    # re-downloading costs nothing extra and isn't a distinct tracked
    # action in this app today (the /artifacts static mount has no
    # per-download accounting - see its own docstring in app/main.py).
    query_limit: int | None
    document_limit: int | None
    features: list[str]
    tagline: str


def _build_plans() -> dict[str, Plan]:
    return {
        "basic": Plan(
            key="basic", label="Basic", amount=settings.paystack_plan_amount_basic,
            paystack_plan_code=settings.paystack_plan_code_basic,
            seat_limit=3, connection_limit=3,
            query_limit=50, document_limit=20,
            tagline="For a small team getting started with AI-driven analytics.",
            features=[
                "Ask & Risk Scan across your connected data",
                "Document intelligence (PDF, Word, PowerPoint, Excel)",
                "Row- and column-level access control",
                "Full hash-chained audit trail",
                "Up to 3 team seats",
                "Up to 3 connected data sources",
                "Up to 50 questions a month",
                "Up to 20 report/presentation downloads a month",
            ],
        ),
        "pro": Plan(
            key="pro", label="Pro", amount=settings.paystack_plan_amount_pro,
            paystack_plan_code=settings.paystack_plan_code_pro,
            seat_limit=10, connection_limit=10,
            query_limit=150, document_limit=100,
            tagline="For a growing team working across more data and more people.",
            features=[
                "Everything in Basic",
                "Up to 10 team seats",
                "Up to 10 connected data sources",
                "Up to 150 questions a month",
                "Up to 100 report/presentation downloads a month",
            ],
        ),
        "premium": Plan(
            key="premium", label="Premium", amount=settings.paystack_plan_amount_premium,
            paystack_plan_code=settings.paystack_plan_code_premium,
            seat_limit=None, connection_limit=None,
            query_limit=None, document_limit=None,
            tagline="For larger teams that need the whole organization on it.",
            features=[
                "Everything in Pro",
                "Unlimited team seats",
                "Unlimited connected data sources",
                "Unlimited questions a month",
                "Unlimited report/presentation downloads a month",
            ],
        ),
    }


# Built once at import time from settings, matching how the rest of this
# app treats settings as fixed for the process's lifetime (e.g.
# rate_limit.py's module-level limiter instances).
PLANS: dict[str, Plan] = _build_plans()


def get_plan(key: str) -> Plan | None:
    return PLANS.get(key)


def seat_limit_for(plan_key: str | None) -> int | None:
    """1 for no plan (free tier - matches the cap already enforced before
    this module existed), else that plan's seat_limit (None = unlimited)."""
    if not plan_key:
        return 1
    plan = PLANS.get(plan_key)
    return plan.seat_limit if plan else 1


def connection_limit_for(plan_key: str | None) -> int | None:
    """Free tier never reaches this check at all (require_active_subscription
    blocks connection creation entirely before any limit would matter),
    but 0 is the honest answer if it somehow did."""
    if not plan_key:
        return 0
    plan = PLANS.get(plan_key)
    return plan.connection_limit if plan else 0


def query_limit_for(plan_key: str | None) -> int | None:
    """Same free-tier reasoning as connection_limit_for above - ask_stream
    is already gated behind require_active_subscription, so a free tenant
    never reaches this check at all; 0 is just the honest answer."""
    if not plan_key:
        return 0
    plan = PLANS.get(plan_key)
    return plan.query_limit if plan else 0


def document_limit_for(plan_key: str | None) -> int | None:
    """Same reasoning again - a free tenant can never have a QueryRecord to
    generate a document FROM in the first place (ask_stream is gated),
    so this never actually matters for free, but 0 is the honest answer."""
    if not plan_key:
        return 0
    plan = PLANS.get(plan_key)
    return plan.document_limit if plan else 0
