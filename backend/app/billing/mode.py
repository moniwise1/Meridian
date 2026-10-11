"""Payment mode checks without exposing credentials."""
def billing_mode(s):
    if s.environment == "production" or s.kms_provider == "aws":
        return "live"
    if s.billing_mode in ("live", "test"):
        return s.billing_mode
    return "live" if s.paystack_secret_key.startswith("sk_live_") else "test"


def validate_billing_config(s):
    errors = []
    if s.billing_mode not in ("auto", "live", "test"):
        errors.append("BILLING_MODE must be auto, live, or test")
    mode = billing_mode(s)
    if (s.environment == "production" or s.kms_provider == "aws") and s.billing_mode == "test":
        errors.append("production cannot use BILLING_MODE=test")
    if s.paystack_secret_key and not s.paystack_secret_key.startswith(f"sk_{mode}_"):
        errors.append(f"PAYSTACK_SECRET_KEY must be a {mode} secret key")
    if s.paystack_public_key and not s.paystack_public_key.startswith(f"pk_{mode}_"):
        errors.append(f"PAYSTACK_PUBLIC_KEY must be a {mode} public key")
    if s.billing_mode == "live" and not s.paystack_secret_key:
        errors.append("live billing requires PAYSTACK_SECRET_KEY")
    if len(s.billing_currency) != 3 or not s.billing_currency.isalpha() or not s.billing_currency.isupper():
        errors.append("BILLING_CURRENCY must be a three-letter uppercase currency code")
    return errors
