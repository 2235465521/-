"""省/市列表缓存（Redis + 内存，避免每次 DISTINCT 扫百万行）。"""

from __future__ import annotations

import threading
import time
from typing import Any

from food_inspection.redis_cache import get_json as redis_get_json
from food_inspection.redis_cache import set_json as redis_set_json

_META_TTL_SEC = 86400
_memory: dict[str, tuple[float, list[str]]] = {}
_memory_lock = threading.Lock()


def _memory_get(key: str) -> list[str] | None:
    with _memory_lock:
        item = _memory.get(key)
    if not item:
        return None
    ts, data = item
    if time.time() - ts > _META_TTL_SEC:
        return None
    return list(data)


def _memory_set(key: str, items: list[str]) -> None:
    with _memory_lock:
        _memory[key] = (time.time(), list(items))


def _redis_key(kind: str, scope: str = "") -> str:
    return f"meta:{kind}:{scope}" if scope else f"meta:{kind}"


def _load_cached(kind: str, scope: str = "") -> list[str] | None:
    mem_key = f"{kind}:{scope}"
    cached = _memory_get(mem_key)
    if cached:
        return cached
    payload = redis_get_json(_redis_key(kind, scope))
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list) and items:
        _memory_set(mem_key, [str(x) for x in items])
        return [str(x) for x in items]
    return None


def _store_cached(kind: str, items: list[str], scope: str = "") -> list[str]:
    mem_key = f"{kind}:{scope}"
    _memory_set(mem_key, items)
    redis_set_json(
        _redis_key(kind, scope),
        {"items": items, "cached_at": time.time()},
        ttl_sec=_META_TTL_SEC,
    )
    return items


def invalidate_meta_cache() -> None:
    with _memory_lock:
        _memory.clear()


def get_provinces() -> list[str]:
    cached = _load_cached("provinces")
    if cached:
        return cached

    try:
        from food_inspection.stats_store import read_provinces, stats_tables_ready

        if stats_tables_ready():
            items = read_provinces()
            if items:
                return _store_cached("provinces", items)
    except Exception:
        pass

    try:
        from food_inspection.mysql_stats import get_mysql_stats

        stats = get_mysql_stats()
        provinces = stats.get("provinces") if isinstance(stats, dict) else None
        if isinstance(provinces, dict) and provinces:
            return _store_cached("provinces", sorted(provinces.keys()))
    except Exception:
        pass

    from food_inspection.db import list_provinces as _list_provinces_db

    return _store_cached("provinces", _list_provinces_db())


def get_cities(province: str = "全部") -> list[str]:
    scope = province or "全部"
    cached = _load_cached("cities", scope)
    if cached:
        return cached

    try:
        from food_inspection.stats_store import read_cities, stats_tables_ready

        if stats_tables_ready():
            items = read_cities(scope)
            if items:  # 如果预统计表中的城市列表为空，则不使用，继续向下走从主表中查询
                return _store_cached("cities", items, scope)
    except Exception:
        pass

    from food_inspection.db import list_cities as _list_cities_db

    return _store_cached("cities", _list_cities_db(scope), scope)


def warm_meta_cache() -> dict[str, Any]:
    provinces = get_provinces()
    cities_all = get_cities("全部")
    return {
        "provinces": len(provinces),
        "cities_all": len(cities_all),
    }
