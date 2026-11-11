"""Password hashing, tokens and rate limiting (all local, no external services)."""

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 recommendations)

# A valid hash used to keep login timing similar for unknown usernames.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_invite_code() -> str:
    # Human friendly: 4 groups of 4 chars, unambiguous alphabet. ~80 bits.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def normalise_invite_code(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RateLimiter:
    """In-memory sliding-window limiter. Good enough for a single-process,
    small-group deployment; resets when the server restarts."""

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def is_limited(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            self._prune(q, now)
            return len(q) >= self.max_events

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            self._prune(q, now)
            q.append(now)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


# 10 failed logins per 15 minutes per IP, and per username.
login_failures = RateLimiter(max_events=10, window_seconds=15 * 60)
# 10 registration attempts per hour per IP (invite-code guessing protection).
register_attempts = RateLimiter(max_events=10, window_seconds=60 * 60)
