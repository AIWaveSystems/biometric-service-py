import threading
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ApiClient
from .security import parse_api_key, verify_api_secret

CACHE_TTL_SECONDS = 60
LAST_USED_INTERVAL_SECONDS = 300

_cache: dict[str, tuple[float, int | None, str, list[str], datetime | None]] = {}
_cache_lock = threading.Lock()
_last_used: dict[int, float] = {}


def invalidate_cache(prefix: str | None = None) -> None:
    with _cache_lock:
        if prefix is None:
            _cache.clear()
        else:
            _cache.pop(prefix, None)


def _touch_last_used(db: Session, client: ApiClient) -> None:
    now = time.monotonic()
    previous = _last_used.get(client.id)
    if previous is not None and now - previous < LAST_USED_INTERVAL_SECONDS:
        return
    _last_used[client.id] = now
    client.last_used_at = datetime.utcnow()
    db.commit()


def resolve_api_key(db: Session, raw: str) -> tuple[int, str, list[str]] | None:
    parsed = parse_api_key(raw)
    if parsed is None:
        return None
    prefix, secret = parsed

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(prefix)
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        _, client_id, key_hash, scopes, expires_at = cached
        if client_id is None or not verify_api_secret(secret, key_hash):
            return None
        if expires_at is not None and datetime.utcnow() >= expires_at:
            return None
        return client_id, prefix, scopes

    client = db.execute(
        select(ApiClient).where(ApiClient.key_prefix == prefix, ApiClient.active.is_(True))
    ).scalar_one_or_none()

    with _cache_lock:
        if client is None:
            _cache[prefix] = (now, None, "", [], None)
        else:
            _cache[prefix] = (now, client.id, client.key_hash, client.scope_list, client.expires_at)

    if client is None or not verify_api_secret(secret, client.key_hash):
        return None
    if client.expired:
        return None

    _touch_last_used(db, client)
    return client.id, prefix, client.scope_list
