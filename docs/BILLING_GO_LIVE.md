# Billing: going live on Paystack

The billing code doesn't change between test and live — it reads whichever
Paystack keys are in the environment. Going live is an env-var swap plus
re-doing the plan and webhook setup in live mode (Paystack keeps test and
live data completely separate).

The full lifecycle (subscribe → hosted checkout → server-side verify →
webhook activation → cancel + refund) was verified end to end in **test
mode** against the real Paystack API on 2026-09-10. This page is the live
cutover.

## 0. Prerequisite — an activated Paystack business account

Paystack won't issue `sk_live_` keys until your business is verified. For a
Nigerian company that means:

- **Certificate of Incorporation** + **RC number**
- **TIN**
- A **corporate bank account** in the company's name (this is where
  settlements land)
- Directors' IDs
- Possibly **SCUML** (EFCC) depending on how Paystack categorises the
  business

So the live key is gated on the same CAC/bank milestone as everything else.

## 1. Get the live keys

Paystack dashboard → toggle from **Test** to **Live** (top of the
dashboard) → **Settings → API Keys & Webhooks** → copy the **Live Secret
Key** (`sk_live_…`) and **Live Public Key** (`pk_live_…`).

## 2. Create the three plans in live mode

Same script as test, with the live key. It needs `--yes` because it's
creating real plans:

```bash
cd backend
PAYSTACK_SECRET_KEY=sk_live_xxxxx python scripts/paystack_plans.py --yes
```

It prints the three new `PLN_…` codes and the exact env vars to set. If you
want different prices than the ₦5,000 / ₦9,999 / ₦25,000 defaults, set
`PAYSTACK_PLAN_AMOUNT_BASIC` / `_PRO` / `_PREMIUM` (in kobo) before running
it, and set the same values on the backend.

## 3. Swap the env vars on Railway

Railway → **backend** service → **Variables**. Replace these five with the
live values from step 2:

```
PAYSTACK_SECRET_KEY=sk_live_...
PAYSTACK_PUBLIC_KEY=pk_live_...
PAYSTACK_PLAN_CODE_BASIC=PLN_...      (live)
PAYSTACK_PLAN_CODE_PRO=PLN_...        (live)
PAYSTACK_PLAN_CODE_PREMIUM=PLN_...    (live)
```

Let it redeploy.

## 4. Set the live webhook URL

Paystack (Live mode) → **Settings → API Keys & Webhooks** → **Webhook
URL**:

```
https://<your-backend-domain>/billing/webhook
```

The webhook signature is verified with `PAYSTACK_SECRET_KEY`, so once
that's the live key, verification uses the right secret automatically —
nothing else to configure.

## 5. Confirm the config took

```bash
curl -s https://<your-backend-domain>/billing/plans | python -m json.tool
```

All three plans should show `"configured": true`.

## 6. One real transaction

Test mode can't prove real settlement or a real card's auth flow (OTP /
3-D Secure). Do one real subscription:

1. Register a workspace (or use your own), go to **Billing**, subscribe to
   the cheapest plan.
2. Pay with a **real card** — you'll get the real OTP/bank prompt.
3. Confirm in the app that the plan shows **active**.
4. Confirm in the Paystack **Live** dashboard that the transaction shows
   **success** and the subscription is **active**.
5. The next business day, confirm the amount (minus Paystack's fee) lands
   in your bank account.
6. Then cancel it from the app while inside the 7-day window and confirm
   the refund appears in the Paystack dashboard (real refunds take a few
   days to settle back).

Once that's clean, real customers can subscribe.

## Rolling back

If something's wrong, put the `sk_test_` / `pk_test_` keys and the test
`PLN_…` codes back on Railway and redeploy — you're back in test mode with
no data loss. Any tenant that subscribed on the live keys keeps its
`subscription_status` in the metadata DB (the DB doesn't distinguish test
from live), so only roll back before real customers have paid.

## Notes

- **Amounts must match.** `PAYSTACK_PLAN_AMOUNT_*` (or the defaults) must
  equal what each live plan is actually set to in Paystack, in kobo. The
  script warns if an existing plan's amount disagrees.
- **Fees.** Paystack's Nigerian card fee (currently ~1.5% + ₦100, capped;
  waived under a threshold) comes out of the settlement, not the charge —
  the customer pays the full plan price, you receive slightly less.
- **The test plans and test data stay** on the test side of your Paystack
  account, untouched. Keep them for future test-mode work.
