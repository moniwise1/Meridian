"""
Create (or verify) Meridian's three Paystack subscription plans and print
the env vars to set on the backend.

Paystack keeps TEST and LIVE data completely separate, so this is run once
per mode: once with the sk_test_ key while you build and test, and again
with the sk_live_ key the day you go live (see docs/BILLING_GO_LIVE.md).

    # test mode - runs freely
    PAYSTACK_SECRET_KEY=sk_test_xxx python scripts/paystack_plans.py

    # live mode - creates REAL plans, so it needs an explicit --yes
    PAYSTACK_SECRET_KEY=sk_live_xxx python scripts/paystack_plans.py --yes

Idempotent: a plan whose name already exists is reused, never duplicated
(it warns if that plan's amount differs from what's configured here).

Plan prices come from PAYSTACK_PLAN_AMOUNT_BASIC / _PRO / _PREMIUM if set
(kobo, matching app/config.py), else the same defaults the app uses. Set
those env vars on the backend too if you change a price, so the app and
Paystack agree.

stdlib only (urllib) - no dependency on the app or on httpx, so it runs
anywhere Python does.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://api.paystack.co"

# (env var, plan key, Paystack plan name, default amount in kobo)
PLAN_SPEC = [
    ("PAYSTACK_PLAN_AMOUNT_BASIC", "basic", "Meridian Basic", 500_000),      # NGN 5,000
    ("PAYSTACK_PLAN_AMOUNT_PRO", "pro", "Meridian Pro", 999_900),            # NGN 9,999
    ("PAYSTACK_PLAN_AMOUNT_PREMIUM", "premium", "Meridian Premium", 2_500_000),  # NGN 25,000
]

KEY = os.environ.get("PAYSTACK_SECRET_KEY", "").strip()
if not KEY:
    sys.exit("Set PAYSTACK_SECRET_KEY in the environment first (sk_test_... or sk_live_...).")

if KEY.startswith("sk_test_"):
    MODE, PUB_PREFIX, SETTINGS_TAB = "TEST", "pk_test_", "Test"
elif KEY.startswith("sk_live_"):
    MODE, PUB_PREFIX, SETTINGS_TAB = "LIVE", "pk_live_", "Live"
    if "--yes" not in sys.argv:
        sys.exit(
            "This is a LIVE key - it will create real plans on your live Paystack\n"
            "account. Re-run with --yes once you're sure:\n"
            "    PAYSTACK_SECRET_KEY=sk_live_xxx python scripts/paystack_plans.py --yes"
        )
else:
    sys.exit(f"Unrecognised key prefix ({KEY[:8]}...). Expected sk_test_ or sk_live_.")


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            # Paystack sits behind Cloudflare, which 403s the default
            # "Python-urllib/3.x" User-Agent (Cloudflare error 1010).
            "User-Agent": "Mozilla/5.0 (compatible; meridian-paystack-plans/1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Paystack {method} {path} -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")


def amount_for(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"{env_var}={raw!r} is not an integer number of kobo.")


print(f"Mode: {MODE}\n")

if not api("GET", "/balance").get("status"):
    sys.exit("Key rejected by Paystack.")
print("1. OK  key works\n")

existing = api("GET", "/plan?perPage=200").get("data", [])
by_name = {p["name"]: p for p in existing}
print(f"2. account has {len(existing)} plan(s) already\n")

print("3. ensuring the three Meridian plans exist:")
resolved: dict[str, str] = {}
for env_var, key, name, default_amount in PLAN_SPEC:
    amount = amount_for(env_var, default_amount)
    match = by_name.get(name)
    if match:
        resolved[key] = match["plan_code"]
        note = ""
        if match["amount"] != amount:
            note = (f"  !! Paystack has this at {match['amount']} kobo, config wants {amount} - "
                    f"fix one so they agree")
        print(f"     {key:8} -> {match['plan_code']}  (exists){note}")
        continue
    created = api("POST", "/plan", {
        "name": name, "amount": amount, "interval": "monthly", "currency": "NGN",
    })["data"]
    resolved[key] = created["plan_code"]
    print(f"     {key:8} -> {created['plan_code']}  (created, NGN {amount // 100:,}/mo)")

print(f"""
4. Set these on the Railway BACKEND service (Variables tab), then redeploy:

   PAYSTACK_SECRET_KEY={KEY}
   PAYSTACK_PUBLIC_KEY={PUB_PREFIX}...   (Paystack > Settings > API Keys & Webhooks)
   PAYSTACK_PLAN_CODE_BASIC={resolved['basic']}
   PAYSTACK_PLAN_CODE_PRO={resolved['pro']}
   PAYSTACK_PLAN_CODE_PREMIUM={resolved['premium']}

5. In Paystack > Settings > API Keys & Webhooks, on the *{SETTINGS_TAB}* side,
   set the Webhook URL to:

   https://<your-backend-domain>/billing/webhook

   (GET https://<your-backend-domain>/billing/plans should then show all
   three plans with "configured": true.)
""")
