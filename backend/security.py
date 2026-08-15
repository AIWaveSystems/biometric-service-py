import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

SCOPE_PORTAL = "portal"
SCOPE_USER = "user"

API_KEY_PREFIX_BYTES = 6
API_KEY_SECRET_BYTES = 32
API_KEY_LABEL = "lbs"


def hash_api_secret(secret: str) -> str:
    pepper = settings.api_key_pepper or settings.jwt_secret
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(API_KEY_PREFIX_BYTES)
    secret = secrets.token_urlsafe(API_KEY_SECRET_BYTES)
    return f"{API_KEY_LABEL}_{prefix}_{secret}", prefix, hash_api_secret(secret)


def parse_api_key(raw: str) -> tuple[str, str] | None:
    parts = raw.strip().split("_", 2)
    if len(parts) != 3 or parts[0] != API_KEY_LABEL or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def verify_api_secret(secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_api_secret(secret), expected_hash)


def create_portal_token(username: str = "portal", user_uuid: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "uid": user_uuid,
        "scope": SCOPE_PORTAL,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_session_token(username: str, method: str, user_uuid: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "uid": user_uuid,
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
