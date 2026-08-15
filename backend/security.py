import hashlib
import hmac
import threading
import time
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

SCOPE_PORTAL = "portal"
SCOPE_USER = "user"


def _encode(subject: str, scope: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_portal_token() -> str:
    return _encode("portal", SCOPE_PORTAL, settings.jwt_expire_minutes)


def create_session_token(username: str, method: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "scope": SCOPE_USER,
        "method": method,
        "iat": now,
        "exp": now + timedelta(minutes=settings.session_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_scope: str | None = None) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "scope"]},
        )
    except jwt.PyJWTError:
        return None
    if expected_scope is not None and payload.get("scope") != expected_scope:
        return None
    return payload


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class ReplayGuard:
    def __init__(self, window_seconds: int):
        self._window = window_seconds
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [k for k, ts in self._seen.items() if now - ts > self._window]
        for k in expired:
            del self._seen[k]

    def check_and_register(self, namespace: str, payloads: list[bytes]) -> bool:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        for chunk in payloads:
            digest.update(hashlib.sha256(chunk).digest())
        key = digest.hexdigest()
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            if key in self._seen:
                return False
            self._seen[key] = now
        return True


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self._window]
            if len(hits) >= self._limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
        return True


replay_guard = ReplayGuard(settings.replay_window_seconds)
auth_limiter = RateLimiter(settings.auth_rate_limit, settings.auth_rate_window_seconds)
