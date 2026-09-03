"""
Login-attempt cooldown - brute-force / credential-stuffing protection for
both login endpoints (`POST /auth/login` and `POST /platform/login`).
Neither had any protection against repeated password guessing before this;
for a SaaS asking enterprise customers to trust it with their data, that's
close to a table-stakes gap any real security review would flag.

The design is deliberately tuned around one constraint the rest of this
module's callers care about as much as the security property itself: a
lockout that ever traps a genuine, paying customer out of their own account
is a support ticket at best and a cancellation at worst. So:

- Keyed by the account identifier being attempted (email), never by IP.
  Locking a shared office/VPN/NAT IP would collateral-damage every other
  person behind it; keying by account only ever slows down someone
  actually guessing *that* account, which is exactly the threat this
  exists to blunt.
- The first `login_free_attempts` failures cost nothing at all - typos,
  autofill pulling a stale password, caps-lock, a second account's
  password muscle-memory - none of that should ever be visibly throttled.
- After that, the cooldown escalates (doubling) but is capped at
  `login_cooldown_max_seconds` and NEVER refuses a correct password
  outright - it only delays the next attempt. A genuine account owner can
  always still get in; an automated guesser attempting thousands of
  passwords pays an increasingly large, bounded-but-real time cost per
  guess, which is what makes brute-forcing infeasible without ever
  making the account unrecoverable.
- A successful login immediately clears all history for that key.
- History for a key that stops seeing failures expires after
  `login_cooldown_reset_after_seconds`, so this stays bounded in memory
  and one bad evening doesn't echo for months.

Same honest limitation as app/security/rate_limit.py: this state is a
plain dict guarded by a lock, held in this worker process's memory only -
not shared across processes or replicas. Behind multiple workers, each
enforces its own independent counter, so the real-world protection is
weaker than the configured numbers suggest (an attacker spread across
worker connections gets `free_attempts x workers` free guesses, not just
`free_attempts`). A production multi-instance deployment needs a shared
store (Redis, or the metadata DB) for this to be a genuine global limit -
not implemented here, tracked as the same category of gap the README
already calls out for rate_limit.py and the query cache.
"""
import threading
import time

from app.config import settings


class LoginCooldownActive(Exception):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(retry_after_seconds, 0.0)
        super().__init__(
            f"Too many failed attempts. Try again in {self._human(self.retry_after_seconds)}."
        )

    @staticmethod
    def _human(seconds: float) -> str:
        seconds = int(seconds + 0.999)  # round up - never tell someone "0s" while still blocked
        if seconds < 60:
            return f"{seconds}s"
        minutes, rem = divmod(seconds, 60)
        return f"{minutes}m {rem}s" if rem else f"{minutes}m"


class _LoginCooldownGuard:
    def __init__(self, free_attempts: int, base_seconds: float, max_seconds: float, reset_after_seconds: float):
        self._free_attempts = free_attempts
        self._base = base_seconds
        self._max = max_seconds
        self._reset_after = reset_after_seconds
        # key -> (failure_count, cooldown_until_monotonic, last_failure_monotonic)
        self._state: dict[str, tuple[int, float, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(key: str) -> str:
        return key.strip().lower()

    def check(self, key: str) -> None:
        """Raise LoginCooldownActive if `key` is currently in a cooldown
        window. Call before checking the password."""
        key = self._normalize(key)
        now = time.monotonic()
        with self._lock:
            entry = self._state.get(key)
            if entry is None:
                return
            count, cooldown_until, last_failure = entry
            if now - last_failure > self._reset_after:
                del self._state[key]
                return
            if now < cooldown_until:
                raise LoginCooldownActive(cooldown_until - now)

    def record_failure(self, key: str) -> None:
        key = self._normalize(key)
        now = time.monotonic()
        with self._lock:
            entry = self._state.get(key)
            if entry is None or now - entry[2] > self._reset_after:
                count = 0
            else:
                count = entry[0]
            count += 1

            if count < self._free_attempts:
                # Still within the free budget - this failure sets no
                # cooldown, so the very next attempt goes straight to
                # password verification with no delay.
                cooldown_until = now
            else:
                # This failure is the one that exhausts (or has already
                # exhausted) the free budget: set a cooldown that blocks
                # the *next* attempt outright, before it ever reaches
                # password verification - see check() below, and point 4
                # of the module docstring on why that matters (it's what
                # actually stops a lucky/automated guess, not just wrong
                # ones). Escalates by doubling each time a cooldown is
                # earned again, capped at `max`.
                exponent = count - self._free_attempts
                delay = min(self._base * (2 ** exponent), self._max)
                cooldown_until = now + delay

            self._state[key] = (count, cooldown_until, now)

    def record_success(self, key: str) -> None:
        key = self._normalize(key)
        with self._lock:
            self._state.pop(key, None)


_tenant_login_guard = _LoginCooldownGuard(
    free_attempts=settings.login_free_attempts,
    base_seconds=settings.login_cooldown_base_seconds,
    max_seconds=settings.login_cooldown_max_seconds,
    reset_after_seconds=settings.login_cooldown_reset_after_seconds,
)
_platform_login_guard = _LoginCooldownGuard(
    free_attempts=settings.login_free_attempts,
    base_seconds=settings.login_cooldown_base_seconds,
    max_seconds=settings.login_cooldown_max_seconds,
    reset_after_seconds=settings.login_cooldown_reset_after_seconds,
)


def check_tenant_login_cooldown(email: str) -> None:
    _tenant_login_guard.check(email)


def record_tenant_login_failure(email: str) -> None:
    _tenant_login_guard.record_failure(email)


def record_tenant_login_success(email: str) -> None:
    _tenant_login_guard.record_success(email)


def check_platform_login_cooldown(email: str) -> None:
    _platform_login_guard.check(email)


def record_platform_login_failure(email: str) -> None:
    _platform_login_guard.record_failure(email)


def record_platform_login_success(email: str) -> None:
    _platform_login_guard.record_success(email)
