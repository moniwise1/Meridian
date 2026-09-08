# Security-regression checks

One `verify_*.py` per fix from the 2026-09 security review. Each runs
standalone against a real SQLite database and a real FastAPI `TestClient`
— the DB layer is never mocked; only the warehouse connector and the
Anthropic calls are stubbed. Several also assert the **pre-fix** code
would have failed, so they can't pass vacuously.

Run them all:

```bash
cd backend
python tests/run_regressions.py
```

or one at a time:

```bash
cd backend
PYTHONPATH=. python tests/verify_billing_binding.py
```

CI (`.github/workflows/ci.yml`) runs `run_regressions.py` on every PR.

| script | guards |
| --- | --- |
| `verify_conversation_id_fix.py` | first question in a thread gets a real `conversation_id` (#40) |
| `verify_tenant_name_trim.py` | a whitespace-padded tenant name stays deletable (#41) |
| `verify_artifact_auth.py` | generated artifacts served only via a signed, tenant-checked token (#42) |
| `verify_billing_binding.py` | `/billing/verify` bound to the caller's own checkout (#43) |
| `verify_mfa_ratelimit.py` | self-service MFA `/confirm` + `/disable` code checks are throttled (#44) |
| `verify_error_sanitization.py` | `/ask` `/scan` + insight step don't leak raw exceptions (#45) |
| `verify_bootstrap_token.py` | `/platform/bootstrap` needs `PLATFORM_BOOTSTRAP_TOKEN` (#46) |
| `verify_startup_config.py` | production refuses to boot with collapsed secrets (#47) |
| `verify_ssrf.py` | connection host can't resolve to a private/metadata address (#48) |
| `verify_http_hardening.py` | security headers on every response; `/docs` off in prod (#49) |
| `verify_auth_abuse.py` | per-IP login guard + `/auth/register` rate limit (#50, #11, #12) |
| `verify_email_policy.py` | tenant outbound-email policy is enforced in `send_report` (#51) |
| `verify_auth_lows.py` | PBKDF2 600k + versioned hash + rehash-on-login; email case-insensitivity (#52) |
| `verify_misc_lows.py` | `limit` params clamped; per-tenant document cap (#53) |
