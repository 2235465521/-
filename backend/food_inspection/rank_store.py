"""榜单预聚合表读写（stats_rank_cache）。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from food_inspection.db import connection
from food_inspection.mysql_search import mysql_enabled
from food_inspection.redis_cache import get_json as redis_get_json
from food_inspection.redis_cache import set_json as redis_set_json
from food_inspection.stats_store import stats_tables_ready


def rank_tables_ready() -> bool:
    """健康检查：全国 + 各省榜单缓存是否齐全（含「全部」）。"""
    if not stats_tables_ready():
        return False
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  SUM(province = '全部') AS has_all,
                  COUNT(*) AS row_count
                FROM stats_rank_cache
                WHERE city = ''
                """
            )
            row = cur.fetchone() or {}
            return bool(row.get("has_all")) and int(row.get("row_count") or 0) >= 30
    except Exception:
        return False


def _scope_rank_cached(province: str, city: str) -> bool:
    """当前省/市范围是否已有预聚合榜单（不依赖「全部」是否就绪）。"""
    scope = _cache_scope(province, city)
    if not scope or not stats_tables_ready():
        return False
    prov, c = scope
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM stats_rank_cache
                WHERE province = %s AND city = %s
                LIMIT 1
                """,
                (prov, c),
            )
            return bool(cur.fetchone())
    except Exception:
        return False


def extract_units_payload(analytics: dict[str, Any]) -> dict[str, Any]:
    return {
        "province": analytics.get("province") or "全部",
        "city": analytics.get("city") or "全部",
        "total": int(analytics.get("total") or 0),
        "top_failure_companies": analytics.get("top_failure_companies") or [],
        "top_failure_manufacturers": analytics.get("top_failure_manufacturers") or [],
        "perfect_companies": analytics.get("perfect_companies") or [],
        "perfect_manufacturers": analytics.get("perfect_manufacturers") or [],
        "repeat_companies": analytics.get("repeat_companies") or [],
        "cities": analytics.get("cities") or [],
        "repeat_company_count": int(analytics.get("repeat_company_count") or 0),
        "perfect_company_count": int(analytics.get("perfect_company_count") or 0),
        "perfect_manufacturer_count": int(analytics.get("perfect_manufacturer_count") or 0),
        "data_source": "mysql_rank_tables",
    }


def extract_products_payload(analytics: dict[str, Any]) -> dict[str, Any]:
    from food_inspection.analytics import refresh_analytics_failure_names

    res = refresh_analytics_failure_names(analytics)
    return _sync_product_item_totals(
        {
            "province": res.get("province") or "全部",
            "city": res.get("city") or "全部",
            "total": int(res.get("total") or 0),
            "top_failure_products": res.get("top_failure_products") or [],
            "repeat_products": res.get("repeat_products") or [],
            "item_types": res.get("item_types") or [],
            "item_types_total": res.get("item_types_total"),
            "item_types_unique": res.get("item_types_unique"),
            "repeat_product_count": int(res.get("repeat_product_count") or 0),
            "data_source": "mysql_rank_tables",
        }
    )


def _sync_product_item_totals(payload: dict[str, Any]) -> dict[str, Any]:
    """与 /api/stats 对齐不合格项次，修正旧 analytics 缓存 total 偏低。"""
    from food_inspection.analytics import _authoritative_item_event_total

    if not payload:
        return payload

    authoritative = _authoritative_item_event_total(payload)
    current = int(payload.get("item_types_total") or payload.get("total") or 0)
    if authoritative <= 0 or authoritative == current:
        return payload

    out = dict(payload)
    out["total"] = authoritative
    out["item_types_total"] = authoritative

    item_types = [dict(row) for row in (out.get("item_types") or [])]
    slice_sum = sum(int(row.get("count") or 0) for row in item_types)
    delta = authoritative - slice_sum
    if delta and item_types:
        other_idx = next(
            (i for i, row in enumerate(item_types) if (row.get("name") or "") == "其他"),
            None,
        )
        if other_idx is not None:
            item_types[other_idx]["count"] = int(item_types[other_idx].get("count") or 0) + delta
        else:
            item_types.append({"name": "其他", "count": delta, "ratio": 0.0})

    for row in item_types:
        count = int(row.get("count") or 0)
        row["ratio"] = round(count / authoritative * 100, 2) if authoritative else 0.0
    out["item_types"] = item_types
    return out


def _cache_scope(province: str, city: str) -> tuple[str, str] | None:
    if city and city != "全部":
        return None
    return (province or "全部", "")


def _redis_key(kind: str, province: str, city: str) -> str:
    return f"rank:{kind}:{province or '全部'}:{city or ''}"


def _read_rank_row(province: str, city: str) -> dict[str, Any] | None:
    scope = _cache_scope(province, city)
    if not scope:
        return None
    prov, c = scope
    units_cached = redis_get_json(_redis_key("units", prov, c))
    products_cached = redis_get_json(_redis_key("products", prov, c))
    if units_cached and products_cached:
        return {"units_json": units_cached, "products_json": products_cached}
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT units_json, products_json, refreshed_at
                FROM stats_rank_cache
                WHERE province = %s AND city = %s
                """,
                (prov, c),
            )
            row = cur.fetchone()
        if not row:
            return None
        units = row.get("units_json")
        products = row.get("products_json")
        if isinstance(units, str):
            units = json.loads(units)
        if isinstance(products, str):
            products = json.loads(products)
        redis_set_json(_redis_key("units", prov, c), units, ttl_sec=86400)
        redis_set_json(_redis_key("products", prov, c), products, ttl_sec=86400)
        return {
            "units_json": units,
            "products_json": products,
            "refreshed_at": row.get("refreshed_at"),
        }
    except Exception:
        return None


def _needs_live_compute(
    province: str,
    city: str,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    if not mysql_enabled():
        return True
    if date_from or date_to:
        return True
    if city and city != "全部":
        return True
    if not _scope_rank_cached(province, city):
        return True
    return False


def _fallback_analytics(
    province: str,
    city: str,
    date_from: str | None,
    date_to: str | None,
) -> dict[str, Any] | None:
    if mysql_enabled():
        from food_inspection.mysql_stats import get_mysql_analytics

        mysql_result = get_mysql_analytics(
            province or "全部",
            city or "全部",
            min_violations=2,
            min_repeat_violations=5,
            date_from=date_from,
            date_to=date_to,
        )
        if mysql_result:
            return mysql_result

    from food_inspection import store

    result = store.get_analytics(
        province or "全部",
        city or "全部",
        2,
        min_repeat_violations=5,
        date_from=date_from,
        date_to=date_to,
    )
    if not result or result.get("loading"):
        return None
    return result


_LIVE_RANK_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_LIVE_RANK_CACHE_LOCK = threading.Lock()
_LIVE_RANK_CACHE_TTL = 1800  # 30 minutes


def _get_live_rank_cache(key: str) -> dict[str, Any] | None:
    now = time.time()
    with _LIVE_RANK_CACHE_LOCK:
        if key in _LIVE_RANK_CACHE:
            ts, val = _LIVE_RANK_CACHE[key]
            if now - ts < _LIVE_RANK_CACHE_TTL:
                return val
            del _LIVE_RANK_CACHE[key]

    redis_val = redis_get_json(key)
    if redis_val:
        with _LIVE_RANK_CACHE_LOCK:
            _LIVE_RANK_CACHE[key] = (now, redis_val)
        return redis_val
    return None


def _set_live_rank_cache(key: str, val: dict[str, Any]) -> None:
    if not val or val.get("loading"):
        return
    now = time.time()
    with _LIVE_RANK_CACHE_LOCK:
        _LIVE_RANK_CACHE[key] = (now, val)
    redis_set_json(key, val, ttl_sec=_LIVE_RANK_CACHE_TTL)


def read_unit_ranks(
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any] | None:
    cache_key = f"rank_units_query:{province}:{city}:{date_from or ''}:{date_to or ''}"
    cached = _get_live_rank_cache(cache_key)
    if cached:
        return cached

    if _needs_live_compute(province, city, date_from, date_to):
        analytics = _fallback_analytics(province, city, date_from, date_to)
        if not analytics:
            return None
        payload = extract_units_payload(analytics)
        payload["data_source"] = analytics.get("data_source") or "mysql"
        _set_live_rank_cache(cache_key, payload)
        return payload

    row = _read_rank_row(province, city)
    if not row:
        analytics = _fallback_analytics(province, city, date_from, date_to)
        if not analytics:
            return None
        payload = extract_units_payload(analytics)
        payload["data_source"] = analytics.get("data_source") or "mysql"
        _set_live_rank_cache(cache_key, payload)
        return payload

    units = row.get("units_json")
    if isinstance(units, str):
        units = json.loads(units)
    if units:
        _set_live_rank_cache(cache_key, units)
    return units


def read_product_ranks(
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any] | None:
    cache_key = f"rank_products_query:{province}:{city}:{date_from or ''}:{date_to or ''}"
    cached = _get_live_rank_cache(cache_key)
    if cached:
        return cached

    if _needs_live_compute(province, city, date_from, date_to) or (province and province != "全部"):
        analytics = _fallback_analytics(province, city, date_from, date_to)
        if not analytics:
            return None
        payload = extract_products_payload(analytics)
        payload["data_source"] = analytics.get("data_source") or "mysql"
        _set_live_rank_cache(cache_key, payload)
        return payload

    row = _read_rank_row(province, city)
    if not row:
        analytics = _fallback_analytics(province, city, date_from, date_to)
        if not analytics:
            return None
        payload = extract_products_payload(analytics)
        payload["data_source"] = analytics.get("data_source") or "mysql"
        _set_live_rank_cache(cache_key, payload)
        return payload

    products = row.get("products_json")
    if isinstance(products, str):
        products = json.loads(products)
    from food_inspection.analytics import refresh_analytics_failure_names

    if isinstance(products, dict):
        products = refresh_analytics_failure_names(products)
    res = _sync_product_item_totals(products)
    if res:
        _set_live_rank_cache(cache_key, res)
    return res
