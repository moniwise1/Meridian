"""
Runs every verify_*.py security-regression check in this directory, each in
its own process (they set their own env + SQLite temp DB and are written to
run standalone), and exits non-zero if any fail.

    cd backend && python tests/run_regressions.py

These are the checks written while working through the 2026-09 security
review - one per fix (authenticated artifact downloads, billing-verify
binding, MFA rate-limiting, SSRF guard, the outbound-email policy, the
PBKDF2/format bump, ...). They use a real SQLite DB + a real FastAPI
TestClient (no mocking of the DB layer); the only things stubbed are the
warehouse connector and the Anthropic calls. Run in CI on every PR.
"""
import pathlib
import subprocess
import sys
import time

TESTS_DIR = pathlib.Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent


def main() -> int:
    scripts = sorted(TESTS_DIR.glob("verify_*.py"))
    if not scripts:
        print("no verify_*.py scripts found", file=sys.stderr)
        return 1

    env = {**__import__("os").environ, "PYTHONPATH": str(BACKEND_DIR)}
    env.setdefault("APP_SECRET_KEY", "dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA=")  # 32 b64 bytes, test-only

    failures = []
    for script in scripts:
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(script)], cwd=BACKEND_DIR, env=env,
            capture_output=True, text=True,
        )
        secs = time.monotonic() - started
        ok = proc.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {script.name}  ({secs:.0f}s)")
        if not ok:
            failures.append(script.name)
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:], file=sys.stderr)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print(f"all {len(scripts)} regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
