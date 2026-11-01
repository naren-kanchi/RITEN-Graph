"""Cache-aside over Redis. An optimization only: every failure path falls back to the database."""
import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable

import redis
from fastapi.encoders import jsonable_encoder

from . import db
from .config import get_settings

log = logging.getLogger("riten.cache")
SCHEMA_VERSION = "v1"
_PREFETCH_MARKER = "riten:prefetched:"
_RETRY_AFTER_FAILURE_SECONDS = 5.0
_MAX_PAYLOAD_BYTES = 2_000_000
_VERSION_TTL_SECONDS = 5.0

_lock = threading.Lock()
_client: redis.Redis | None = None
_down_until = 0.0
_version: tuple[float, str] = (0.0, "")
stats = {"hit": 0, "miss": 0, "bypass": 0, "error": 0, "oversize": 0, "prefetch_used": 0}


def _count(name: str) -> None:
    with _lock:
        stats[name] += 1


def _redis() -> redis.Redis | None:
    global _client
    s = get_settings()
    if not s.cache_enabled or time.monotonic() < _down_until:
        return None
    if _client is None:
        _client = redis.Redis.from_url(s.redis_url, socket_timeout=0.25, socket_connect_timeout=0.25)
    return _client


def _mark_down(exc: Exception) -> None:
    global _down_until
    _down_until = time.monotonic() + _RETRY_AFTER_FAILURE_SECONDS
    _count("error")
    log.warning("redis unavailable, using the database: %s", type(exc).__name__)


def current_version() -> str:
    """The dataset version is part of every key, so a new import can never serve old results."""
    global _version
    now = time.monotonic()
    if now - _version[0] > _VERSION_TTL_SECONDS:
        _version = (now, db.data_version())
    return _version[1]


def make_key(view: str, params: dict[str, Any], version: str | None = None) -> str:
    canonical = json.dumps({k: params[k] for k in sorted(params)}, default=str, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    return f"riten:{SCHEMA_VERSION}:{version or current_version()}:{view}:{digest}"


def _record_prefetch_use(key: str) -> None:
    _count("prefetch_used")
    try:
        with db.transaction() as conn:
            conn.execute(
                """UPDATE prefetch_stat SET used_at = now() WHERE prefetch_id = (
                       SELECT prefetch_id FROM prefetch_stat WHERE cache_key = %s AND used_at IS NULL
                       ORDER BY prefetched_at DESC LIMIT 1)""", (key,))
    except Exception:
        log.exception("could not record prefetch use")


def cached(view: str, params: dict[str, Any], compute: Callable[[], Any], ttl: int | None = None) -> tuple[Any, str]:
    """Return (payload, 'HIT' | 'MISS' | 'BYPASS'). The payload is always JSON-compatible."""
    client = _redis()
    if client is None:
        _count("bypass")
        return jsonable_encoder(compute()), "BYPASS"
    key = make_key(view, params)
    try:
        pipe = client.pipeline(transaction=False)
        pipe.get(key)
        pipe.getdel(_PREFETCH_MARKER + key)
        raw, marker = pipe.execute()
        if raw is not None:
            _count("hit")
            if marker is not None:
                _record_prefetch_use(key)
            return json.loads(raw), "HIT"
    except redis.RedisError as exc:
        _mark_down(exc)
        return jsonable_encoder(compute()), "BYPASS"
    payload = jsonable_encoder(compute())
    _count("miss")
    store(key, payload, ttl)
    return payload, "MISS"


def store(key: str, payload: Any, ttl: int | None = None, prefetched: bool = False) -> int:
    """Write a bounded payload. Returns bytes stored, or 0 when skipped."""
    client = _redis()
    if client is None:
        return 0
    body = json.dumps(payload, separators=(",", ":"))
    if len(body) > _MAX_PAYLOAD_BYTES:
        _count("oversize")
        return 0
    seconds = ttl or get_settings().cache_ttl_seconds
    try:
        pipe = client.pipeline(transaction=False)
        pipe.set(key, body, ex=seconds)
        if prefetched:
            pipe.set(_PREFETCH_MARKER + key, "1", ex=seconds)
        pipe.execute()
    except redis.RedisError as exc:
        _mark_down(exc)
        return 0
    return len(body)


def exists(key: str) -> bool:
    client = _redis()
    if client is None:
        return False
    try:
        return bool(client.exists(key))
    except redis.RedisError as exc:
        _mark_down(exc)
        return False


def ping() -> bool:
    if not get_settings().cache_enabled:
        return False
    try:
        return bool(redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.25, socket_connect_timeout=0.25).ping())
    except redis.RedisError:
        return False


def reset_for_tests() -> None:
    global _client, _down_until, _version
    _client, _down_until, _version = None, 0.0, (0.0, "")
    for k in stats:
        stats[k] = 0
