#!/usr/bin/env python3
"""将磁盘缓存同步到 Redis，并预热全国 analytics（若缺失）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401

from config import ROOT_DIR
from food_inspection.redis_cache import full_key, is_redis_available, redis_enabled, set_json
from food_inspection.region_cache import _REGION_CACHE_VERSION, _region_disk_dir


def _sync_region_disk() -> int:
    disk_dir = Path(_region_disk_dir())
    if not disk_dir.is_dir():
        return 0
    count = 0
    for path in disk_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("cache_version") or 0) != _REGION_CACHE_VERSION:
                continue
            key = path.stem
            if set_json(f"region:{key}", payload, ttl_sec=86400):
                count += 1
        except Exception:
            continue
    return count


def _sync_analytics_disk() -> int:
    disk_dir = Path(ROOT_DIR) / "data" / "analytics_disk_cache"
    if not disk_dir.is_dir():
        return 0
    count = 0
    for path in disk_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if set_json(f"analytics:{path.stem}", payload, ttl_sec=86400):
                count += 1
        except Exception:
            continue
    return count


def _sync_mysql_stats() -> bool:
    stats_path = Path(ROOT_DIR) / "data" / "mysql_stats_cache.json"
    if not stats_path.is_file():
        return False
    try:
        payload = json.loads(stats_path.read_text(encoding="utf-8"))
        return set_json("mysql_stats", payload, ttl_sec=86400)
    except Exception:
        return False


def _warm_analytics_if_missing() -> bool:
    from food_inspection.store import (
        _ANALYTICS_CACHE_VERSION,
        _read_analytics_disk,
        _write_analytics_disk,
    )

    key = ("全部", "全部", _ANALYTICS_CACHE_VERSION, 2, 5, "", "")
    if _read_analytics_disk(key):
        return True
    print("  计算全国 analytics…", flush=True)
    from food_inspection.mysql_stats import get_mysql_analytics

    result = get_mysql_analytics("全部", "全部", 2, 5, None, None)
    if not result:
        return False
    _write_analytics_disk(key, result)
    return True


def _warm_meta_lists() -> dict[str, Any]:
    from food_inspection.region_meta import warm_meta_cache

    print("  预热省/市列表…", flush=True)
    return warm_meta_cache()


def _warm_list_pages() -> dict[str, int]:
    from food_inspection.mysql_search import mysql_enabled, search_records

    if not mysql_enabled():
        return {}
    print("  预热列表第 1-2 页…", flush=True)
    warmed: dict[str, int] = {}
    for status in ("qualified", "unqualified"):
        for page in (1, 2):
            result = search_records(
                status=status,
                province="全部",
                city="全部",
                page=page,
                page_size=30,
                skip_total=True,
            )
            warmed[f"{status}:{page}"] = len(result.get("items") or [])
    return warmed


def main() -> int:
    if not redis_enabled():
        print("REDIS_URL 未配置，跳过 Redis 预热")
        return 0
    if not is_redis_available():
        print("Redis 不可用，跳过预热")
        return 1

    region_n = _sync_region_disk()
    analytics_n = _sync_analytics_disk()
    stats_ok = _sync_mysql_stats()
    meta = _warm_meta_lists()
    list_pages = _warm_list_pages()
    analytics_ok = _warm_analytics_if_missing()

    print(
        f"Redis 预热完成：region {region_n} 条，analytics {analytics_n} 条，"
        f"stats={'OK' if stats_ok else 'skip'}，"
        f"provinces={meta.get('provinces', 0)} cities={meta.get('cities_all', 0)}，"
        f"list_pages={sum(list_pages.values())} 条，"
        f"全国 analytics={'OK' if analytics_ok else 'pending'}",
        flush=True,
    )
    print(f"  前缀示例: {full_key('region:')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
