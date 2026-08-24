"""省级地图 / 城市洞察接口的内存 + Redis + 磁盘缓存。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Callable

from config import ROOT_DIR
from food_inspection.redis_cache import get_json as redis_get_json
from food_inspection.redis_cache import set_json as redis_set_json

_REGION_CACHE_VERSION = 2
_REGION_CACHE_TTL_SEC = 86400
def _region_disk_dir() -> str:
    return os.environ.get(
        "REGION_CACHE_DIR",
        os.path.join(ROOT_DIR, "data", "region_disk_cache"),
    )

_MAX_REGION_COMPUTE = max(1, int(os.environ.get("REGION_CACHE_MAX_CONCURRENT", "2")))

_memory: dict[str, tuple[float, dict[str, Any]]] = {}
_memory_lock = threading.Lock()
_compute_jobs: set[str] = set()
_compute_lock = threading.Lock()
_compute_slots = threading.Semaphore(_MAX_REGION_COMPUTE)


def _cache_key(kind: str, *parts: Any) -> str:
    raw = json.dumps((kind, *parts), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _disk_path(key: str) -> str:
    disk_dir = _region_disk_dir()
    os.makedirs(disk_dir, exist_ok=True)
    return os.path.join(disk_dir, f"{key}.json")


def _read_disk(key: str) -> dict[str, Any] | None:
    path = _disk_path(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if int(payload.get("cache_version") or 0) != _REGION_CACHE_VERSION:
            return None
        if time.time() - float(payload.get("cached_at") or 0) > _REGION_CACHE_TTL_SEC:
            return None
        data = payload.get("data")
        return dict(data) if isinstance(data, dict) else None
    except Exception:
        return None


def _redis_key(key: str) -> str:
    return f"region:{key}"


def _read_redis(key: str) -> dict[str, Any] | None:
    payload = redis_get_json(_redis_key(key))
    if not payload:
        return None
    if int(payload.get("cache_version") or 0) != _REGION_CACHE_VERSION:
        return None
    if time.time() - float(payload.get("cached_at") or 0) > _REGION_CACHE_TTL_SEC:
        return None
    data = payload.get("data")
    return dict(data) if isinstance(data, dict) else None


def _write_redis(key: str, data: dict[str, Any]) -> None:
    redis_set_json(
        _redis_key(key),
        {
            "cache_version": _REGION_CACHE_VERSION,
            "cached_at": time.time(),
            "data": data,
        },
        ttl_sec=_REGION_CACHE_TTL_SEC,
    )


def _write_disk(key: str, data: dict[str, Any]) -> None:
    try:
        with open(_disk_path(key), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "cache_version": _REGION_CACHE_VERSION,
                    "cached_at": time.time(),
                    "data": data,
                },
                handle,
                ensure_ascii=False,
            )
    except Exception:
        pass


def _read_memory(key: str) -> dict[str, Any] | None:
    with _memory_lock:
        item = _memory.get(key)
    if not item:
        return None
    ts, data = item
    if time.time() - ts > _REGION_CACHE_TTL_SEC:
        return None
    return dict(data)


def _write_memory(key: str, data: dict[str, Any]) -> None:
    with _memory_lock:
        _memory[key] = (time.time(), dict(data))


def _write_cached(key: str, data: dict[str, Any]) -> None:
    _write_memory(key, data)
    _write_redis(key, data)
    _write_disk(key, data)


def get_or_compute(
    key: str,
    compute: Callable[[], dict[str, Any] | None],
    *,
    loading_factory: Callable[[], dict[str, Any]] | None = None,
    allow_async: bool = True,
) -> dict[str, Any] | None:
    """先读缓存；未命中时同步计算，或后台计算并返回 loading。"""
    cached = _read_memory(key) or _read_redis(key) or _read_disk(key)
    if cached:
        _write_memory(key, cached)
        return cached

    if allow_async and loading_factory is not None:
        with _compute_lock:
            if key in _compute_jobs:
                return loading_factory()
            _compute_jobs.add(key)

        def _run() -> None:
            with _compute_slots:
                try:
                    result = compute()
                    if result:
                        _write_cached(key, result)
                finally:
                    with _compute_lock:
                        _compute_jobs.discard(key)

        threading.Thread(target=_run, daemon=True, name=f"region-cache-{key[:8]}").start()
        return loading_factory()

    result = compute()
    if result:
        _write_cached(key, result)
    return result


def map_loading_payload(province: str, city: str = "") -> dict[str, Any]:
    return {
        "loading": True,
        "message": "地图统计计算中，请稍候…",
        "scope": province if province != "全部" else "全国",
        "level": "city" if province != "全部" else "province",
        "regions": [],
        "max_failure_rate": 0,
        "min_failure_rate": 0,
        "data_source": "mysql",
        "province": province,
        "city": city,
    }


def insights_loading_payload(province: str, city: str) -> dict[str, Any]:
    return {
        "loading": True,
        "message": "城市榜单计算中，请稍候…",
        "province": province,
        "city": city,
        "qualified_count": 0,
        "unqualified_count": 0,
        "total_count": 0,
        "failure_rate": 0,
        "top_risk_companies": [],
        "top_risk_products": [],
        "top_safe_companies": [],
        "top_safe_products": [],
    }
