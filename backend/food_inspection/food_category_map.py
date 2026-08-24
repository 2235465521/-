"""食品原名 → 大类/小类 映射查询。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _load_map() -> dict[str, tuple[str, str]]:
    try:
        from food_inspection.db import connection

        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT food_name_original, category_major, category_minor
                FROM dim_food_category_map
                WHERE category_minor IS NOT NULL AND TRIM(category_minor) <> ''
                """
            )
            rows = cur.fetchall()
        out: dict[str, tuple[str, str]] = {}
        for row in rows:
            key = (row.get("food_name_original") or "").strip()
            if not key:
                continue
            major = (row.get("category_major") or "").strip()
            minor = (row.get("category_minor") or "").strip()
            if minor:
                out[key] = (major, minor)
        return out
    except Exception:
        return {}


def invalidate_map_cache() -> None:
    _load_map.cache_clear()


def lookup_categories(food_name: str) -> tuple[str, str] | None:
    key = (food_name or "").strip()
    if not key:
        return None
    hit = _load_map().get(key)
    if not hit:
        return None
    major, minor = hit
    if not minor:
        return None
    return major, minor


def lookup_sub_category(food_name: str) -> str:
    hit = lookup_categories(food_name)
    return hit[1] if hit else ""


def lookup_major_category(food_name: str) -> str:
    hit = lookup_categories(food_name)
    return hit[0] if hit else ""


def is_mapped_food_name(food_name: str) -> bool:
    return bool(lookup_sub_category(food_name))


def record_is_mapped(record: dict[str, Any]) -> bool:
    sub = (record.get("sub_category") or "").strip()
    if sub:
        return True
    return is_mapped_food_name((record.get("product") or record.get("food_name") or "").strip())
