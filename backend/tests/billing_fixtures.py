from datetime import datetime, timezone
from app.billing.plans import get_plan, plan_key_for_paystack_code, interval_for_paystack_code, amount_for
from app.db.models import BillingPayment, Tenant


def payment_fixture(data, db):
    data = dict(data)
    raw = data.get("plan")
    code = raw.get("plan_code") if isinstance(raw, dict) else raw
    receipt = db.get(BillingPayment, data.get("reference"))
    tenant = db.get(Tenant, (data.get("metadata") or {}).get("tenant_id"))
    plan = get_plan(plan_key_for_paystack_code(code) if code else receipt.plan if receipt else tenant.plan)
    interval = interval_for_paystack_code(code) if code else receipt.interval if receipt else tenant.billing_interval or "monthly"
    return {"status": "success", "domain": "test", "currency": "NGN",
            "amount": amount_for(plan, interval),
            "paid_at": datetime.now(timezone.utc).isoformat(), **data}


def webhook_fixture(payload, db):
    if payload.get("event") == "charge.success":
        return {**payload, "data": payment_fixture(payload["data"], db)}
    return payload
