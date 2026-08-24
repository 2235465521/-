"""列表分页结果 Redis 缓存（仅缓存常见无关键词查询）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from food_inspection.redis_cache import get_json as redis_get_json
from food_inspection.redis_cache import set_json as redis_set_json

_LIST_CACHE_TTL_SEC = 600
_LIST_CACHE_VERSION = 5


def _norm(value: Any) -> str:
    return str(value or "").strip()


def is_cacheable_list_query(
    *,
    status: str = "qualified",
    province: str = "全部",
    city: str = "全部",
    county: str = "",
    year: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    company: str = "",
    product: str = "",
    category: str = "",
    item: str = "",
    reason: str = "",
    q: str = "",
    entity_role: str = "",
    page: int = 1,
    page_size: int = 50,
    skip_total: bool = False,
    **_: Any,
) -> bool:
    if page > 5 or page < 1:
        return False
    if any(
        _norm(value)
        for value in (
            county,
            year,
            company,
            product,
            category,
            item,
            reason,
            q,
            entity_role,
            date_from,
            date_to,
        )
    ):
        return False
    return True


def list_cache_key(
    *,
    status: str,
    province: str = "全部",
    city: str = "全部",
    page: int = 1,
    page_size: int = 50,
    skip_total: bool = False,
    **extra: Any,
) -> str:
    payload = {
        "v": _LIST_CACHE_VERSION,
        "status": _norm(status) or "qualified",
        "province": _norm(province) or "全部",
        "city": _norm(city) or "全部",
        "page": int(page),
        "page_size": int(page_size),
        "skip_total": bool(skip_total),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()[:20]
    return f"list:{digest}"


def get_cached_list(key: str) -> dict[str, Any] | None:
    payload = redis_get_json(key)
    if not payload or int(payload.get("cache_version") or 0) != _LIST_CACHE_VERSION:
        return None
    data = payload.get("data")
    return dict(data) if isinstance(data, dict) else None


def set_cached_list(key: str, data: dict[str, Any]) -> None:
    redis_set_json(
        key,
        {"cache_version": _LIST_CACHE_VERSION, "data": data},
        ttl_sec=_LIST_CACHE_TTL_SEC,
    )
