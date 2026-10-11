# Live billing safety patch

## Deploy

1. Back up the metadata database before deployment.
2. Apply this patch to the repository and deploy both services.
3. On the Railway backend set `BILLING_MODE=live` and `BILLING_CURRENCY=NGN`.
   Keep `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY` set to the matching
   live keys from the same Paystack business. Rotate any exposed secret.
4. Configure live Paystack plan codes for each offered monthly/annual plan;
   prices must agree with the backend amounts. Test plan codes cannot be
   reused on live credentials. No plans or charges are created by this patch.
5. Confirm the frontend's `NEXT_PUBLIC_API_BASE` points to that backend.
6. Set the Paystack Live webhook to
   `https://meridian-production-5e3f.up.railway.app/billing/webhook`.
7. After deployment, GET `/billing/config` should return
   `{"mode":"live","currency":"NGN","configured":true}`.
8. Start a fresh checkout and manually complete one real payment. Confirm it
   in Paystack's Live dashboard and confirm subscription activation.

`BILLING_MODE=live` is independent of the existing `ENVIRONMENT=production`
KMS requirements. Production/real-KMS deployments require live billing even
with `BILLING_MODE=auto`. A configured test or mismatched public key prevents
startup; no credentials are exposed in diagnostics.

## Database changes

Startup creates the `billing_payments` table and adds nullable
`tenants.payment_mode` through the existing additive migration mechanism.
No old subscriptions, payments or customer records are deleted or reset.
A checkout stores its expected amount, currency, plan, interval and mode.
Verified payments record live/test mode and are applied only once per
reference, across webhook retries and browser verification. Renewal prices
use a preceding recorded payment to preserve grandfathered pricing.

## Existing test subscriptions

A legacy subscription has unknown mode (`payment_mode=NULL`). Do not assume
it is a real payment, and do not assume it is test. Check its reference in
Paystack before changing access. For an account confirmed to be test-only,
use the existing platform administration controls to change its subscription
status to `none`, then start a fresh live checkout. Do not refund a test
reference using live credentials. Preserve genuine paid subscriptions and
intentional complimentary access. There is no automatic destructive cleanup.

A pending legacy checkout may need manual reconciliation if its old reference
cannot be verified after the switch. Validate the reference in the correct
Paystack environment before changing its status.

## Validation and limitations

Payment verification and signed charge webhooks now require success, the
matching live/test domain, exact expected amount/currency and a valid payment
timestamp. Duplicate payments cannot extend access or reactivate a cancelled
subscription. Expired and known wrong-mode subscriptions lose paid access;
the Billing page offers a fresh checkout.

Legacy renewals without a preceding recorded payment are checked against
current configured prices. If an existing customer has an older price,
reconcile that customer's actual payment before deployment; this patch must
not guess their historical price. Unknown legacy mode is preserved, rather
than revoking existing customers automatically.

Subscription periods still use this repository's 30/365-day convention,
anchored to the payment timestamp. Calendar-exact renewal dates and proration
are not implemented here. No live payment or settlement was executed during
validation; transport calls were mocked.
