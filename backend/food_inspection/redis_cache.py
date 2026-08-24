"""Redis JSON 缓存（可选；连接失败时静默降级，不影响现有磁盘缓存）。"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

_client: Any = None
_client_lock = threading.Lock()
_available: bool | None = None


def redis_enabled() -> bool:
    if os.environ.get("DISABLE_REDIS", "").strip().lower() in ("1", "true", "yes"):
        return False
    return bool(
        os.environ.get("REDIS_URL", "").strip()
        or os.environ.get("REDIS_HOST", "").strip()
    )


def _key_prefix() -> str:
    return os.environ.get("REDIS_KEY_PREFIX", "shipin:")


def full_key(key: str) -> str:
    prefix = _key_prefix()
    return key if key.startswith(prefix) else f"{prefix}{key}"


def _get_client() -> Any | None:
    global _client, _available
    if not redis_enabled():
        _available = False
        return None
    with _client_lock:
        if _available is False:
            return None
        if _client is not None:
            return _client
        try:
            import redis

            url = os.environ.get("REDIS_URL", "").strip()
            if url:
                _client = redis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=5,
                )
            else:
                _client = redis.Redis(
                    host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    db=int(os.environ.get("REDIS_DB", "0")),
                    password=os.environ.get("REDIS_PASSWORD") or None,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=5,
                )
            _client.ping()
            _available = True
        except Exception:
            _available = False
            _client = None
            return None
        return _client


def is_redis_available() -> bool:
    return _get_client() is not None


def get_json(key: str) -> dict[str, Any] | None:
    client = _get_client()
    if not client:
        return None
    try:
        raw = client.get(full_key(key))
        if not raw:
            return None
        data = json.loads(raw)
        return dict(data) if isinstance(data, dict) else None
    except Exception:
        return None


def set_json(key: str, data: dict[str, Any], *, ttl_sec: int | None = None) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        payload = json.dumps(data, ensure_ascii=False)
        redis_key = full_key(key)
        if ttl_sec and ttl_sec > 0:
            client.setex(redis_key, ttl_sec, payload)
        else:
            client.set(redis_key, payload)
        return True
    except Exception:
        return False


def delete_prefix(prefix: str) -> int:
    """删除某前缀下所有键（用于清缓存）。"""
    client = _get_client()
    if not client:
        return 0
    try:
        pattern = full_key(f"{prefix}*")
        deleted = 0
        for key in client.scan_iter(match=pattern, count=200):
            deleted += int(client.delete(key) or 0)
        return deleted
    except Exception:
        return 0
