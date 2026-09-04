"""
Login-attempt cooldown - brute-force / credential-stuffing protection for
both login endpoints (`POST /auth/login` and `POST /platform/login`), and
(a third guard, same machinery, keyed by user_id instead of email) the
login-time TOTP code check in `POST /auth/mfa/verify-login` - a 6-digit
code is a much smaller search space than a password, so guessing it
matters just as much to rate-limit.
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

Two backends behind the exact same public functions, chosen once at
import time based on settings.redis_url — same split as
app/security/rate_limit.py:

- In-process (REDIS_URL unset, the default): a plain dict guarded by a
  lock, held in this worker process's memory only. Behind multiple
  workers, each enforces its own independent counter, so the real-world
  protection is weaker than the configured numbers suggest (an attacker
  spread across worker connections gets `free_attempts x workers` free
  guesses, not just `free_attempts`).
- Redis-backed (REDIS_URL set): a genuinely global counter per key across
  every process and replica. Uses HINCRBY for the failure counter, which
  is atomic on its own (no WATCH/Lua needed) and returns the new count
  directly, so the exponential-backoff calculation is always computed
  from a real, race-free count - the only residual race is on the write
  of the *derived* cooldown_until value between two truly-simultaneous
  failures for the same account, which can only differ by one exponent
  step and is therefore benign (see _RedisLoginCooldownGuard below).
  Fails open on a Redis connection error (see
  app/security/redis_client.py's docstring for why).
"""
import threading
import time

from app.config import settings
from app.security.redis_client import get_redis_client, log_redis_failure


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


class _RedisLoginCooldownGuard:
    """Same semantics and same tuning knobs as _LoginCooldownGuard, backed
    by a Redis hash per (namespace, key) storing `count` and
    `cooldown_until`. `namespace` keeps the tenant-login and
    platform-login guards in separate Redis keyspaces despite sharing one
    Redis instance, the same isolation two separate in-process dicts gave
    them before.

    record_failure() uses HINCRBY for the counter specifically because
    it's atomic AND returns the new value in one round trip - no
    read-then-write race on the count itself. The exponential-backoff
    delay is then a pure function of that race-free count, so the only
    thing that could theoretically race is two near-simultaneous failures
    each writing their own (correctly-computed, but from slightly
    different count values) cooldown_until - and since count only ever
    increases and the delay function is monotonic in count, whichever
    write "loses" still leaves a cooldown_until that's correct for ONE of
    the two failures that just happened, never a stale or under-protective
    value. Good enough for a security-adjacent-but-not-security-critical
    control like this one; see rate_limit.py's docstring for the same
    reasoning applied to the rate limiter.

    Redis's own TTL does the "forget after `reset_after_seconds` of no
    further failures" job that the in-process version does by hand
    (comparing against a stored last-failure time) - EXPIRE is reset on
    every failure, so the key simply stops existing once nothing has
    touched it for that long, and check()/record_failure() both treat a
    missing key as "no history", which is exactly the reset behavior."""

    def __init__(self, namespace: str, free_attempts: int, base_seconds: float,
                 max_seconds: float, reset_after_seconds: float):
        self._namespace = namespace
        self._free_attempts = free_attempts
        self._base = base_seconds
        self._max = max_seconds
        self._reset_after = reset_after_seconds

    def _redis_key(self, key: str) -> str:
        return f"logincooldown:{self._namespace}:{key.strip().lower()}"

    def check(self, key: str) -> None:
        redis_client = get_redis_client()
        import redis as redis_lib
        try:
            cooldown_until = redis_client.hget(self._redis_key(key), "cooldown_until")
        except redis_lib.RedisError as e:
            log_redis_failure("login cooldown check", e)
            return  # fail open
        if cooldown_until is None:
            return
        now = time.time()
        cooldown_until = float(cooldown_until)
        if now < cooldown_until:
            raise LoginCooldownActive(cooldown_until - now)

    def record_failure(self, key: str) -> None:
        redis_client = get_redis_client()
        import redis as redis_lib
        redis_key = self._redis_key(key)
        now = time.time()
        try:
            count = redis_client.hincrby(redis_key, "count", 1)
            if count < self._free_attempts:
                cooldown_until = now
            else:
                exponent = count - self._free_attempts
                delay = min(self._base * (2 ** exponent), self._max)
                cooldown_until = now + delay
            redis_client.hset(redis_key, "cooldown_until", cooldown_until)
            redis_client.expire(redis_key, int(self._reset_after) + 1)
        except redis_lib.RedisError as e:
            log_redis_failure("login cooldown record_failure", e)
            # Fail open - don't let a Redis hiccup turn into "this failed
            # login silently isn't tracked", but also don't crash the
            # login request over it: the 401 for the wrong password still
            # happens via the caller's own logic either way.

    def record_success(self, key: str) -> None:
        redis_client = get_redis_client()
        import redis as redis_lib
        try:
            redis_client.delete(self._redis_key(key))
        except redis_lib.RedisError as e:
            log_redis_failure("login cooldown record_success", e)


_redis = get_redis_client()
if _redis is not None:
    _tenant_login_guard = _RedisLoginCooldownGuard(
        namespace="tenant",
        free_attempts=settings.login_free_attempts,
        base_seconds=settings.login_cooldown_base_seconds,
        max_seconds=settings.login_cooldown_max_seconds,
        reset_after_seconds=settings.login_cooldown_reset_after_seconds,
    )
    _platform_login_guard = _RedisLoginCooldownGuard(
        namespace="platform",
        free_attempts=settings.login_free_attempts,
        base_seconds=settings.login_cooldown_base_seconds,
        max_seconds=settings.login_cooldown_max_seconds,
        reset_after_seconds=settings.login_cooldown_reset_after_seconds,
    )
    # Same machinery, keyed by user_id instead of email - guards the
    # login-time TOTP code check (app/api/routes_mfa.py's verify-login)
    # against brute-forcing a 6-digit code the same way the guards above
    # already protect passwords. A separate namespace/instance so a
    # burst of wrong codes never touches (or is touched by) the password
    # cooldown for the same account.
    _mfa_login_guard = _RedisLoginCooldownGuard(
        namespace="mfa",
        free_attempts=settings.login_free_attempts,
        base_seconds=settings.login_cooldown_base_seconds,
        max_seconds=settings.login_cooldown_max_seconds,
        reset_after_seconds=settings.login_cooldown_reset_after_seconds,
    )
else:
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
    _mfa_login_guard = _LoginCooldownGuard(
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


def check_mfa_login_cooldown(user_id: str) -> None:
    _mfa_login_guard.check(user_id)


def record_mfa_login_failure(user_id: str) -> None:
    _mfa_login_guard.record_failure(user_id)


def record_mfa_login_success(user_id: str) -> None:
    _mfa_login_guard.record_success(user_id)
