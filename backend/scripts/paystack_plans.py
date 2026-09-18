"""
Create (or verify) Meridian's three Paystack subscription plans and print
the env vars to set on the backend.

Paystack keeps TEST and LIVE data completely separate, so this is run once
per mode: once with the sk_test_ key while you build and test, and again
with the sk_live_ key the day you go live (see docs/BILLING_GO_LIVE.md).

    # test mode - runs freely (bash / Git Bash)
    PAYSTACK_SECRET_KEY=sk_test_xxx python scripts/paystack_plans.py

    # the same in Windows PowerShell - set the variable first, then run
    $env:PAYSTACK_SECRET_KEY = "sk_test_xxx"; python scripts/paystack_plans.py

    # live mode - creates REAL plans, so it needs an explicit --yes
    PAYSTACK_SECRET_KEY=sk_live_xxx python scripts/paystack_plans.py --yes

Idempotent: a plan whose name already exists is reused, never duplicated.

Changing a price: if a plan exists at a different amount than configured
here, the script only WARNS by default. Add --reprice to update that plan's
amount in place (Paystack's PUT /plan/:code). The plan keeps its plan_code,
so nothing needs changing on the backend's PAYSTACK_PLAN_CODE_* variables.
It is sent with update_existing_subscriptions=false: anyone already
subscribed keeps the price they signed up at, and only NEW subscriptions
pay the new amount - silently raising a paying customer's renewal price is
not something a script should ever do on its own.

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

# (env var, plan key, Paystack plan name, default MONTHLY amount in kobo)
PLAN_SPEC = [
    ("PAYSTACK_PLAN_AMOUNT_BASIC", "basic", "Meridian Basic", 750_000),      # NGN 7,500
    ("PAYSTACK_PLAN_AMOUNT_PRO", "pro", "Meridian Pro", 2_500_000),          # NGN 25,000
    ("PAYSTACK_PLAN_AMOUNT_PREMIUM", "premium", "Meridian Premium", 7_500_000),  # NGN 75,000
]


def annual_amount(monthly_kobo: int, discount_percent: int) -> int:
    """Must stay identical to app/billing/plans.py annual_amount_for - the
    Paystack plan has to charge exactly what the site advertises. Duplicated
    rather than imported because this script deliberately has no dependency
    on the app (see the module docstring)."""
    discounted = monthly_kobo * 12 * (100 - discount_percent) / 100
    return int(round(discounted / 100)) * 100

REPRICE = "--reprice" in sys.argv

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

discount = amount_for("BILLING_ANNUAL_DISCOUNT_PERCENT", 5)

# Every tier needs TWO Paystack plans: Paystack bills a plan at exactly one
# interval, so paying yearly is its own plan on the "annually" interval,
# not the monthly one charged in advance.
wanted = []
for env_var, key, name, default_amount in PLAN_SPEC:
    monthly = amount_for(env_var, default_amount)
    wanted.append((key, name, "monthly", monthly, "mo"))
    wanted.append((f"{key}_annual", f"{name} (Annual)", "annually", annual_amount(monthly, discount), "yr"))

print(f"3. ensuring the six Meridian plans exist (annual = 12 months less {discount}%):")

# Decide everything BEFORE writing anything, so a run that is going to
# refuse (a price mismatch without --reprice) leaves the account exactly as
# it found it rather than half-updated.
plan_actions = []
for key, name, interval, amount, per in wanted:
    match = by_name.get(name)
    if not match:
        plan_actions.append(("create", key, name, interval, amount, per, None))
    elif match["amount"] == amount and match.get("interval", interval) == interval:
        plan_actions.append(("ok", key, name, interval, amount, per, match))
    else:
        plan_actions.append(("reprice", key, name, interval, amount, per, match))

mismatched = [a for a in plan_actions if a[0] == "reprice"]
if mismatched and not REPRICE:
    for _, key, _, interval, amount, per, match in mismatched:
        print(f"     {key:15} -> {match['plan_code']}  !! Paystack has NGN {match['amount'] // 100:,} "
              f"{match.get('interval')}, config wants NGN {amount // 100:,} {interval}")
    sys.exit(
        f"\nPrices disagree for: {', '.join(a[1] for a in mismatched)}. The site would advertise\n"
        f"one price while Paystack charges another. Nothing was changed. Re-run with --reprice\n"
        f"to update those plans in place (existing subscribers keep their old price; plan codes\n"
        f"do not change)."
    )

resolved: dict[str, str] = {}
created_any = False
for action, key, name, interval, amount, per, match in plan_actions:
    if action == "ok":
        resolved[key] = match["plan_code"]
        print(f"     {key:15} -> {match['plan_code']}  (exists, NGN {amount // 100:,}/{per})")
    elif action == "reprice":
        resolved[key] = match["plan_code"]
        api("PUT", f"/plan/{match['plan_code']}", {"amount": amount, "interval": interval,
                                                   "update_existing_subscriptions": False})
        print(f"     {key:15} -> {match['plan_code']}  (repriced NGN {match['amount'] // 100:,} -> "
              f"NGN {amount // 100:,}/{per}; existing subscribers keep their old price)")
    else:
        created = api("POST", "/plan", {
            "name": name, "amount": amount, "interval": interval, "currency": "NGN",
        })["data"]
        created_any = True
        resolved[key] = created["plan_code"]
        print(f"     {key:15} -> {created['plan_code']}  (created, NGN {amount // 100:,}/{per})")

if not created_any:
    print("\n   Plan codes are unchanged. If Railway already has these six codes set,\n"
          "   there is nothing to change there - you're done.")

# The secret key is deliberately NOT echoed back. This output gets
# screenshotted and pasted into chats and tickets; a full sk_live_ key in
# that screenshot is a full compromise of the Paystack account.
print(f"""
4. Set these on the Railway BACKEND service (Variables tab), then redeploy:

   PAYSTACK_SECRET_KEY=<the {MODE.lower()} secret key you just used - not printed here>
   PAYSTACK_PUBLIC_KEY={PUB_PREFIX}...   (Paystack > Settings > API Keys & Webhooks)
   PAYSTACK_PLAN_CODE_BASIC={resolved['basic']}
   PAYSTACK_PLAN_CODE_PRO={resolved['pro']}
   PAYSTACK_PLAN_CODE_PREMIUM={resolved['premium']}
   PAYSTACK_PLAN_CODE_BASIC_ANNUAL={resolved['basic_annual']}
   PAYSTACK_PLAN_CODE_PRO_ANNUAL={resolved['pro_annual']}
   PAYSTACK_PLAN_CODE_PREMIUM_ANNUAL={resolved['premium_annual']}

5. In Paystack > Settings > API Keys & Webhooks, on the *{SETTINGS_TAB}* side,
   set the Webhook URL to:

   https://<your-backend-domain>/billing/webhook

   (GET https://<your-backend-domain>/billing/plans should then show all
   three plans with "configured": true and "annual_configured": true.)
""")
