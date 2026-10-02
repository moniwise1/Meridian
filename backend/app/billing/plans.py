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

Seats and connections are unlimited on Premium because they cost
nothing to serve. QUESTIONS are not, and are capped on every tier
including Premium: each one is a real, variable API spend, and a
document-backed question costs several times a database-backed one
(it ships the whole extracted document text to the reasoning model,
and again on every tool round-trip). An uncapped tier on a variable
cost is an open-ended liability, not a generous feature - see
app/config.py's paystack_plan_amount_* comment for the arithmetic.
document_limit stays unlimited on Premium because generating a report
from an already-computed snapshot makes no model call at all
(report_generator.py / presentation_generator.py are pure rendering).

Free (no paid plan) isn't in PLANS at all - it's the tenant's default
state (Tenant.tier == "free"), already gated out of the core paid actions
entirely by require_active_subscription (app/security/auth.py), with its
own 1-seat cap already enforced in routes_auth.py before this module
existed.
"""
from dataclasses import dataclass
from typing import Literal

from app.config import settings


BillingInterval = Literal["monthly", "annual"]
BILLING_INTERVALS: tuple[str, ...] = ("monthly", "annual")

# How far one successful charge advances subscription_expires_at. Monthly
# stays the 30-day approximation it has always been (see routes_billing.py
# _activate for why it isn't read off Paystack); a year is 365 days. A
# renewal re-reminder fires subscription_expiry_reminder_days before the
# end of either.
_PERIOD_DAYS = {"monthly": 30, "annual": 365}


def period_days(interval: str | None) -> int:
    """NULL/unknown -> monthly, matching Tenant.billing_interval's own
    NULL-means-monthly convention."""
    return _PERIOD_DAYS.get(interval or "monthly", 30)


def refund_window_days(interval: str | None) -> int:
    """Full self-serve refund window after the FIRST payment, by billing
    interval. NULL/unknown -> monthly, matching Tenant.billing_interval.
    The window is anchored on Tenant.paid_at, which is set once ever, so
    renewals - monthly or annual - never reopen it."""
    if interval == "annual":
        return settings.billing_refund_window_days_annual
    return settings.billing_refund_window_days


def annual_amount_for(monthly_kobo: int) -> int:
    """12 months less the configured annual discount, rounded to whole naira
    - every price this app shows is a round naira figure (format_naira), and
    the Paystack plan must match the displayed amount exactly. Derived, never
    configured separately, so a monthly reprice carries the annual price
    with it (see app/config.py billing_annual_discount_percent)."""
    discounted = monthly_kobo * 12 * (100 - settings.billing_annual_discount_percent) / 100
    return int(round(discounted / 100)) * 100


@dataclass
class Plan:
    key: str  # "basic" | "pro" | "premium" - stored on Tenant.plan once subscribed
    label: str
    amount: int  # smallest currency unit (kobo for NGN) - the MONTHLY price
    paystack_plan_code: str  # the monthly Paystack plan
    annual_amount: int  # a year up front, see annual_amount_for
    paystack_annual_plan_code: str  # a separate Paystack plan on the "annually" interval
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
            annual_amount=annual_amount_for(settings.paystack_plan_amount_basic),
            paystack_annual_plan_code=settings.paystack_plan_code_basic_annual,
            seat_limit=3, connection_limit=3,
            query_limit=25, document_limit=20,
            tagline="For a small team getting started with AI-driven analytics.",
            features=[
                "Ask & Risk Scan across your connected data",
                "Document intelligence (PDF, Word, PowerPoint, Excel)",
                "Row- and column-level access control",
                "Full hash-chained audit trail",
                "Up to 3 team seats",
                "Up to 3 connected data sources",
                "Up to 25 questions a month",
                "Up to 20 report/presentation downloads a month",
            ],
        ),
        "pro": Plan(
            key="pro", label="Pro", amount=settings.paystack_plan_amount_pro,
            paystack_plan_code=settings.paystack_plan_code_pro,
            annual_amount=annual_amount_for(settings.paystack_plan_amount_pro),
            paystack_annual_plan_code=settings.paystack_plan_code_pro_annual,
            seat_limit=10, connection_limit=10,
            query_limit=100, document_limit=100,
            tagline="For a growing team working across more data and more people.",
            features=[
                "Everything in Basic",
                "Up to 10 team seats",
                "Up to 10 connected data sources",
                "Up to 100 questions a month",
                "Up to 100 report/presentation downloads a month",
            ],
        ),
        "premium": Plan(
            key="premium", label="Premium", amount=settings.paystack_plan_amount_premium,
            paystack_plan_code=settings.paystack_plan_code_premium,
            annual_amount=annual_amount_for(settings.paystack_plan_amount_premium),
            paystack_annual_plan_code=settings.paystack_plan_code_premium_annual,
            seat_limit=None, connection_limit=None,
            query_limit=300, document_limit=None,
            tagline="For larger teams that need the whole organization on it.",
            features=[
                "Everything in Pro",
                "Unlimited team seats",
                "Unlimited connected data sources",
                "Up to 300 questions a month",
                "Unlimited report/presentation downloads a month",
            ],
        ),

        # Individual plans. Separate keys rather than the same three keys
        # read differently per account type, because every limit in this
        # app is looked up by plan key alone (seat_limit_for and friends
        # below, and their call sites across routes_*). Giving individuals
        # their own keys means a tenant's plan string remains the single
        # answer to "what is this account allowed to do", instead of an
        # answer that is only correct once you also know the account type.
        #
        # One seat throughout, and that is the point of the tier rather
        # than a restriction bolted on: an individual is not paying for
        # seats, so they pay less and get volume instead. Everything that
        # protects data - MFA, row- and column-level scoping, the audit
        # trail - is identical to the business plans. The cheapest tier
        # must not be the insecure one.
        "individual_basic": Plan(
            key="individual_basic", label="Individual Basic",
            amount=settings.paystack_plan_amount_individual_basic,
            paystack_plan_code=settings.paystack_plan_code_individual_basic,
            annual_amount=annual_amount_for(settings.paystack_plan_amount_individual_basic),
            paystack_annual_plan_code=settings.paystack_plan_code_individual_basic_annual,
            seat_limit=1, connection_limit=2,
            query_limit=35, document_limit=35,
            tagline="For one person who needs answers from their own data.",
            features=[
                "Ask & Risk Scan across your connected data",
                "Document intelligence (PDF, Word, PowerPoint, Excel)",
                "Two-factor authentication",
                "Full hash-chained audit trail",
                "Up to 2 connected data sources",
                "Up to 35 questions a month",
                "Up to 35 report/presentation downloads a month",
            ],
        ),
        "individual_pro": Plan(
            key="individual_pro", label="Individual Pro",
            amount=settings.paystack_plan_amount_individual_pro,
            paystack_plan_code=settings.paystack_plan_code_individual_pro,
            annual_amount=annual_amount_for(settings.paystack_plan_amount_individual_pro),
            paystack_annual_plan_code=settings.paystack_plan_code_individual_pro_annual,
            seat_limit=1, connection_limit=5,
            query_limit=75, document_limit=75,
            tagline="For an analyst working across more sources, more often.",
            features=[
                "Everything in Individual Basic",
                "Up to 5 connected data sources",
                "Up to 75 questions a month",
                "Up to 75 report/presentation downloads a month",
            ],
        ),
        "individual_premium": Plan(
            key="individual_premium", label="Individual Premium",
            amount=settings.paystack_plan_amount_individual_premium,
            paystack_plan_code=settings.paystack_plan_code_individual_premium,
            annual_amount=annual_amount_for(settings.paystack_plan_amount_individual_premium),
            paystack_annual_plan_code=settings.paystack_plan_code_individual_premium_annual,
            seat_limit=1, connection_limit=10,
            query_limit=150, document_limit=150,
            tagline="For heavy, daily use by one person.",
            features=[
                "Everything in Individual Pro",
                "Up to 10 connected data sources",
                "Up to 150 questions a month",
                "Up to 150 report/presentation downloads a month",
            ],
        ),
    }


# Which plans belong to which kind of account. A tenant is one or the
# other, and is only ever offered its own catalogue: an individual cannot
# buy seats they are not allowed to fill, and a business should not be
# sold a plan capped at one person.
ACCOUNT_TYPES = ("business", "individual")
BUSINESS_PLAN_KEYS = ("basic", "pro", "premium")
INDIVIDUAL_PLAN_KEYS = ("individual_basic", "individual_pro", "individual_premium")


def normalize_account_type(value: str | None) -> str:
    """NULL/unknown -> business. Every tenant that existed before account
    types did is a business: they were all created with a subdomain and a
    team, which is exactly what a business account is."""
    return value if value in ACCOUNT_TYPES else "business"


def plan_keys_for_account_type(account_type: str | None) -> tuple[str, ...]:
    return (INDIVIDUAL_PLAN_KEYS
            if normalize_account_type(account_type) == "individual"
            else BUSINESS_PLAN_KEYS)


def plans_for_account_type(account_type: str | None) -> list["Plan"]:
    return [PLANS[k] for k in plan_keys_for_account_type(account_type) if k in PLANS]


def account_type_for_plan(plan_key: str | None) -> str:
    """Which kind of account a plan belongs to. Used to stop a tenant
    being put on the other catalogue's plan by hand or by a stale code."""
    return "individual" if (plan_key or "") in INDIVIDUAL_PLAN_KEYS else "business"


# Built once at import time from settings, matching how the rest of this
# app treats settings as fixed for the process's lifetime (e.g.
# rate_limit.py's module-level limiter instances).
PLANS: dict[str, Plan] = _build_plans()


def get_plan(key: str) -> Plan | None:
    return PLANS.get(key)


def format_naira(kobo: int) -> str:
    """kobo (the smallest NGN unit, what `amount` is stored in everywhere)
    -> a human "₦9,999" string for emails / notices. Whole naira only -
    every plan price here is a round naira figure."""
    return f"₦{kobo // 100:,}"


def plan_code_for(plan: Plan, interval: str | None) -> str:
    return plan.paystack_annual_plan_code if interval == "annual" else plan.paystack_plan_code


def amount_for(plan: Plan, interval: str | None) -> int:
    return plan.annual_amount if interval == "annual" else plan.amount


def price_label(plan: Plan, interval: str | None) -> str:
    """"₦85,500/year" or "₦7,500/month" - for notices, emails and the
    platform panel, so none of them can say "/month" to an annual payer."""
    return f"{format_naira(amount_for(plan, interval))}/{'year' if interval == 'annual' else 'month'}"


def _resolve_paystack_code(code: str | None) -> tuple[str, str] | None:
    """(plan key, interval) for a Paystack plan_code, checking both the
    monthly and the annual code of every plan. An unconfigured plan's code
    is "" and must never match, hence the truthiness guards."""
    if not code:
        return None
    for plan in PLANS.values():
        if plan.paystack_plan_code and plan.paystack_plan_code == code:
            return plan.key, "monthly"
        if plan.paystack_annual_plan_code and plan.paystack_annual_plan_code == code:
            return plan.key, "annual"
    return None


def plan_key_for_paystack_code(code: str | None) -> str | None:
    """The reverse of Plan.paystack_plan_code / paystack_annual_plan_code:
    which of our own plan keys ("basic"/"pro"/"premium") a Paystack
    plan_code corresponds to, or None if it matches none. Used by billing
    activation to set Tenant.plan from what a verified transaction actually
    paid for, rather than trusting the value /subscribe optimistically
    wrote before payment."""
    resolved = _resolve_paystack_code(code)
    return resolved[0] if resolved else None


def interval_for_paystack_code(code: str | None) -> str | None:
    """"monthly" / "annual" for a Paystack plan_code, or None if it matches
    no configured plan - same verified-over-optimistic reconciliation as
    plan_key_for_paystack_code, for Tenant.billing_interval."""
    resolved = _resolve_paystack_code(code)
    return resolved[1] if resolved else None


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
