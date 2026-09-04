"""
Billing (premium-from-onset model) — subscribe, verify, cancel/refund, and
the Paystack webhook. See app/billing/paystack.py for the client and the
webhook-signature security note; that signature check is what makes
/billing/webhook safe to expose without authentication at all.

Activation is deliberately reachable from two independent paths -
/verify (the browser redirecting back after checkout) and /webhook
(Paystack's async push) - so a user who closes their browser right after
paying still gets activated once the webhook arrives, and one whose
webhook is delayed gets activated immediately via the redirect. Both call
the same _activate() and are idempotent.

Every state transition here goes through the same hash-chained audit log
as every other consequential action in this app (app/audit/logger.py) -
money moving deserves at least the same trail as a query running.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Tenant, User
from app.security.auth import get_current_user, require_role, AuthContext
from app.billing import paystack
from app.billing.paystack import PaystackError
from app.billing.plans import PLANS, get_plan
from app.audit import logger as audit
from app.config import settings

router = APIRouter(prefix="/billing", tags=["billing"])


class PlanOut(BaseModel):
    key: str
    label: str
    amount: int
    seat_limit: int | None
    connection_limit: int | None
    features: list[str]
    tagline: str
    configured: bool  # False if this plan's Paystack plan code isn't set yet - lets the frontend disable "Subscribe" with a clear reason instead of a confusing checkout failure


@router.get("/plans", response_model=list[PlanOut])
def list_plans():
    """Single source of truth for pricing-card content - see
    app/billing/plans.py. Deliberately public, no auth (unlike every other
    /billing/* route) - it now backs the public marketing landing page's
    pricing section (frontend/components/LandingPage.tsx), and none of
    plan/label/amount/seat_limit/connection_limit/features/tagline/
    configured is tenant-specific or sensitive; it's the same content a
    real SaaS pricing page always shows a logged-out visitor."""
    return [
        PlanOut(
            key=p.key, label=p.label, amount=p.amount, seat_limit=p.seat_limit,
            connection_limit=p.connection_limit, features=p.features, tagline=p.tagline,
            configured=bool(p.paystack_plan_code),
        )
        for p in PLANS.values()
    ]


class BillingStatus(BaseModel):
    subscription_status: str
    tier: str
    plan: str | None
    paid_at: str | None
    refund_eligible_until: str | None
    subscription_expires_at: str | None
    plan_code: str | None


def _status_for(tenant: Tenant) -> BillingStatus:
    refund_eligible_until = None
    if tenant.paid_at and tenant.subscription_status == "active":
        refund_eligible_until = (
            tenant.paid_at + timedelta(days=settings.billing_refund_window_days)
        ).isoformat()
    return BillingStatus(
        subscription_status=tenant.subscription_status,
        tier=tenant.tier,
        plan=tenant.plan,
        paid_at=tenant.paid_at.isoformat() if tenant.paid_at else None,
        refund_eligible_until=refund_eligible_until,
        subscription_expires_at=(
            tenant.subscription_expires_at.isoformat() if tenant.subscription_expires_at else None
        ),
        plan_code=tenant.paystack_plan_code,
    )


@router.get("/status", response_model=BillingStatus)
def get_status(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")
    return _status_for(tenant)


class SubscribeRequest(BaseModel):
    plan: str  # "basic" | "pro" | "premium" - see app/billing/plans.py
    callback_url: str


@router.post("/subscribe")
def subscribe(body: SubscribeRequest, db: Session = Depends(get_db),
              ctx: AuthContext = Depends(require_role("admin"))):
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    user = db.query(User).filter_by(id=ctx.user_id).first()
    if not tenant or not user:
        raise HTTPException(404, "Tenant or user not found.")
    if tenant.subscription_status == "active":
        raise HTTPException(400, "This organization already has an active subscription.")

    plan = get_plan(body.plan)
    if not plan:
        raise HTTPException(400, f"Unknown plan '{body.plan}'. Choose one of: {', '.join(PLANS)}.")
    if not plan.paystack_plan_code:
        raise HTTPException(500, f"The {plan.label} plan is not configured yet (missing its Paystack plan code).")

    try:
        result = paystack.initialize_subscription_transaction(
            email=user.email, plan_code=plan.paystack_plan_code,
            amount=plan.amount, callback_url=body.callback_url,
            metadata={"tenant_id": tenant.id},
        )
    except PaystackError as e:
        audit.log(db, ctx.tenant_id, "subscription_initialize_failed", ctx.user_id,
                   status="error", detail={"reason": str(e), "plan": body.plan})
        raise HTTPException(502, f"Could not start checkout: {e}")

    tenant.subscription_status = "pending"
    # Set now, before checkout even completes - same reasoning as
    # last_transaction_reference below: known regardless of which of the
    # two activation paths (client redirect vs. webhook) lands first, and
    # regardless of whether Paystack's own transaction/subscription data
    # happens to echo a plan code back in a form this app could otherwise
    # parse.
    tenant.plan = body.plan
    tenant.last_transaction_reference = result["reference"]
    db.commit()
    audit.log(db, ctx.tenant_id, "subscription_checkout_started", ctx.user_id,
               detail={"reference": result["reference"], "plan": body.plan})
    return {"authorization_url": result["authorization_url"], "reference": result["reference"]}


def _activate(db: Session, tenant: Tenant, transaction_data: dict, source: str,
              user_id: str | None = None) -> None:
    """Idempotent: calling this twice for the same successful transaction
    just re-confirms the same state, never double-activates or
    double-logs misleadingly."""
    already_active = tenant.subscription_status == "active"
    tenant.subscription_status = "active"
    tenant.last_transaction_reference = transaction_data.get("reference", tenant.last_transaction_reference)
    customer = transaction_data.get("customer") or {}
    if customer.get("customer_code"):
        tenant.paystack_customer_code = customer["customer_code"]
    plan = transaction_data.get("plan")
    if plan:
        tenant.paystack_plan_code = plan.get("plan_code") if isinstance(plan, dict) else plan
    if not tenant.paid_at:
        tenant.paid_at = datetime.utcnow()
    # Unlike paid_at (anchors the refund window - set once, ever), this
    # advances on EVERY successful charge including renewals, so it always
    # reflects the current period's actual end rather than the first one.
    # Approximated as a 30-day cycle since there's no live Paystack account
    # here to confirm the plan's real billing interval or read a renewal
    # date back from - see app/billing/paystack.py's module docstring for
    # the same honest caveat about not being verified against a real
    # account. A production deployment with real recurring billing should
    # instead read the actual next-charge date off the
    # subscription.create / invoice events Paystack sends.
    tenant.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
    db.commit()
    if not already_active:
        audit.log(db, tenant.id, "subscription_activated", user_id, detail={
            "source": source, "reference": transaction_data.get("reference"),
        })


@router.get("/verify")
def verify(reference: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")
    try:
        data = paystack.verify_transaction(reference)
    except PaystackError as e:
        raise HTTPException(502, f"Could not verify payment: {e}")
    if data.get("status") != "success":
        audit.log(db, ctx.tenant_id, "subscription_verify_not_successful", ctx.user_id,
                   status="denied", detail={"reference": reference, "paystack_status": data.get("status")})
        raise HTTPException(400, "Payment was not successful.")
    _activate(db, tenant, data, source="client_verify", user_id=ctx.user_id)
    return _status_for(tenant)


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not paystack.verify_webhook_signature(raw_body, signature):
        # Deliberately no detail about *why* it failed - don't hand an
        # attacker a signature-verification oracle.
        raise HTTPException(401, "Invalid signature.")

    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data") or {}

    # Attribution: prefer the metadata.tenant_id set at /subscribe time
    # (present on charge/transaction events); fall back to
    # paystack_customer_code for events that don't carry metadata through
    # (subscription.* events, per Paystack's docs). The fallback only works
    # once a prior charge.success has already recorded that customer_code
    # on the tenant - true for the normal "charge.success then
    # subscription.create" ordering a new subscription produces, but if
    # Paystack ever delivers subscription.create first, this fallback
    # would miss it. Not verified against a live account - see
    # app/billing/paystack.py's module docstring.
    tenant = None
    metadata = data.get("metadata")
    tenant_id_hint = metadata.get("tenant_id") if isinstance(metadata, dict) else None
    if tenant_id_hint:
        tenant = db.query(Tenant).filter_by(id=tenant_id_hint).first()
    if not tenant:
        customer_code = (data.get("customer") or {}).get("customer_code")
        if customer_code:
            tenant = db.query(Tenant).filter_by(paystack_customer_code=customer_code).first()
    if not tenant:
        # Can't attribute this event to a tenant - ack it anyway (2xx) so
        # Paystack doesn't retry forever, but log it so a human can look.
        audit.log(db, "unknown", "webhook_unattributed", status="error", detail={"event": event})
        return {"status": "ignored"}

    if event == "charge.success":
        _activate(db, tenant, data, source="webhook")
    elif event == "subscription.create":
        tenant.paystack_subscription_code = data.get("subscription_code")
        tenant.paystack_email_token = data.get("email_token")
        plan = data.get("plan") or {}
        tenant.paystack_plan_code = plan.get("plan_code", tenant.paystack_plan_code)
        db.commit()
        audit.log(db, tenant.id, "subscription_created",
                   detail={"subscription_code": tenant.paystack_subscription_code})
    elif event == "subscription.disable":
        tenant.subscription_status = "cancelled"
        tenant.subscription_expires_at = None
        tenant.plan = None
        db.commit()
        audit.log(db, tenant.id, "subscription_disabled_by_paystack", detail={"event": event})
    elif event == "invoice.payment_failed":
        audit.log(db, tenant.id, "subscription_renewal_failed", status="denied", detail={"event": event})
    else:
        audit.log(db, tenant.id, "webhook_unhandled_event", detail={"event": event})

    return {"status": "processed"}


@router.post("/cancel")
def cancel(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("admin"))):
    tenant = db.query(Tenant).filter_by(id=ctx.tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")
    if tenant.subscription_status != "active":
        raise HTTPException(400, "There is no active subscription to cancel.")

    within_refund_window = (
        tenant.paid_at is not None
        and datetime.utcnow() - tenant.paid_at <= timedelta(days=settings.billing_refund_window_days)
    )

    if tenant.paystack_subscription_code and tenant.paystack_email_token:
        try:
            paystack.disable_subscription(tenant.paystack_subscription_code, tenant.paystack_email_token)
        except PaystackError as e:
            audit.log(db, ctx.tenant_id, "subscription_cancel_failed", ctx.user_id,
                       status="error", detail={"reason": str(e)})
            raise HTTPException(502, f"Could not cancel the subscription with Paystack: {e}")
    else:
        # subscription.create's webhook hasn't landed yet (or never will),
        # so there's no subscription_code/email_token to disable with. The
        # tenant is still marked cancelled below, but Paystack's own
        # recurring billing may keep attempting to charge them - flagged
        # loudly rather than silently proceeding as if this were clean.
        audit.log(db, ctx.tenant_id, "subscription_cancel_missing_paystack_handle", ctx.user_id,
                   status="error", detail={"reason": "No paystack_subscription_code/email_token on file."})

    refunded = False
    if within_refund_window and tenant.last_transaction_reference:
        try:
            paystack.refund_transaction(tenant.last_transaction_reference)
            refunded = True
        except PaystackError as e:
            # Subscription is already disabled at this point - don't leave
            # the tenant in limbo over a refund failure, but make sure
            # this is loud in the audit trail so a human follows up.
            audit.log(db, ctx.tenant_id, "refund_failed", ctx.user_id, status="error",
                       detail={"reason": str(e), "reference": tenant.last_transaction_reference})

    tenant.subscription_status = "refunded" if refunded else "cancelled"
    tenant.subscription_expires_at = None
    tenant.plan = None
    db.commit()
    audit.log(db, ctx.tenant_id, "subscription_cancelled", ctx.user_id,
               detail={"refunded": refunded, "within_refund_window": within_refund_window})
    return _status_for(tenant)
