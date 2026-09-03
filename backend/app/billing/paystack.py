"""
Paystack billing client - thin wrapper around the REST API, backing the
premium-from-onset subscription model: a tenant is charged immediately at
signup (not given a delayed-billing free trial), with a self-serve full
refund available if they cancel within
settings.billing_refund_window_days (see app/api/routes_billing.py).

Money amounts: Paystack works in the smallest currency unit throughout -
kobo for NGN, cents for USD, pesewas for GHS, etc. Every `amount` field
here is in that unit, always. This module never divides or multiplies one,
since silently getting that wrong is the single most common real-money bug
in payment integrations (charging 100x or 1/100th of the intended amount).

The single most security-critical function in this whole billing subsystem
is `verify_webhook_signature` below - see its docstring. Get that wrong and
anyone who can reach this app's public webhook URL can forge a
"payment succeeded" event and grant themselves free premium access,
without ever paying Paystack anything.

Honest limitation: none of this has been exercised against a live Paystack
account (no test-mode keys available in this environment) - it's built
strictly to Paystack's documented API contract. `verify_webhook_signature`
is pure HMAC arithmetic and is verified with a real test vector in
tests/test_paystack.py; the HTTP request-shaping functions are verified
against a mocked transport asserting the exact request each one sends, not
against Paystack's real servers. Confirm the first real transaction in
Paystack's dashboard before relying on this in production.
"""
import hashlib
import hmac
import httpx

from app.config import settings

BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
    def __init__(self, message: str, response_body: dict | None = None):
        super().__init__(message)
        self.response_body = response_body or {}


def _headers() -> dict:
    if not settings.paystack_secret_key:
        raise PaystackError("PAYSTACK_SECRET_KEY is not configured.")
    return {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, client: httpx.Client | None = None, **kwargs) -> dict:
    """`client` is injectable purely so tests can pass an
    httpx.Client(transport=httpx.MockTransport(...)) instead of hitting the
    network - production call sites never pass it."""
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.request(method, f"{BASE_URL}{path}", headers=_headers(), **kwargs)
        body = resp.json()
        if not body.get("status"):
            raise PaystackError(body.get("message", "Paystack request failed."), body)
        return body["data"]
    finally:
        if owns_client:
            client.close()


def initialize_subscription_transaction(email: str, plan_code: str, amount: int,
                                         callback_url: str, metadata: dict | None = None,
                                         client: httpx.Client | None = None) -> dict:
    """Starts a hosted-checkout transaction bound to a subscription plan.
    Completing it on Paystack's page both charges the customer immediately
    and creates the Paystack subscription in one step - this app's
    paid-from-onset model, not a delayed free trial. `amount` is passed
    explicitly (matching the plan's real price) even though Paystack's docs
    say `plan` overrides it, since that behavior isn't something this
    integration can verify without a live account - see module docstring.
    Returns {authorization_url, access_code, reference}; redirect the
    browser to authorization_url."""
    return _request("POST", "/transaction/initialize", client=client, json={
        "email": email,
        "amount": amount,
        "plan": plan_code,
        "callback_url": callback_url,
        "metadata": metadata or {},
    })


def verify_transaction(reference: str, client: httpx.Client | None = None) -> dict:
    """Confirms a transaction actually succeeded. Never trust the client's
    redirect back to callback_url by itself - always re-verify server-side
    with Paystack directly, the same "never trust what the client claims"
    discipline app/security/auth.py's docstring describes for identity."""
    return _request("GET", f"/transaction/verify/{reference}", client=client)


def disable_subscription(subscription_code: str, email_token: str,
                          client: httpx.Client | None = None) -> dict:
    return _request("POST", "/subscription/disable", client=client, json={
        "code": subscription_code,
        "token": email_token,
    })


def refund_transaction(transaction_reference: str, client: httpx.Client | None = None) -> dict:
    """Full refund of the named transaction. Paystack also supports a
    partial `amount` - not used here, since this app's refund policy is
    all-or-nothing within the window (see routes_billing.py)."""
    return _request("POST", "/refund", client=client, json={"transaction": transaction_reference})


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Paystack signs every webhook POST body with
    HMAC-SHA512(secret_key, raw_body) in the `x-paystack-signature` header.
    This is the ONLY thing standing between "a real payment happened" and
    "anyone who finds this URL can POST a fake charge.success event and get
    free premium access" - call this before trusting a single field of a
    webhook payload, no exceptions.

    Two details that are easy to get wrong and would silently break this:
    - Must hash the RAW request bytes exactly as received, not a
      re-serialized `json.dumps()` of the parsed body - re-serialization
      can reorder keys or change whitespace, producing different bytes and
      a signature that never matches even for a genuine event.
    - Comparison must be constant-time (hmac.compare_digest, not `==`), so
      this check can't itself be timing-attacked into leaking the correct
      signature one byte at a time.
    """
    if not signature_header or not settings.paystack_secret_key:
        return False
    expected = hmac.new(
        settings.paystack_secret_key.encode(), raw_body, hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
