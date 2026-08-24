#!/usr/bin/env python3
"""预热省级地图与城市洞察磁盘缓存。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401

from food_inspection.mysql_search import mysql_enabled
from food_inspection.mysql_stats import get_mysql_city_insights, get_mysql_overview_map
from food_inspection.region_cache import _cache_key, get_or_compute


def main() -> int:
    if not mysql_enabled():
        print("MySQL 未启用，跳过 region 缓存预热")
        return 0

    provinces = [
        "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省", "黑龙江省",
        "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
        "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省", "重庆市", "四川省", "贵州省",
        "云南省", "西藏自治区", "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",
    ]
    ok = 0
    for province in provinces:
        map_key = _cache_key("map", province, "", "", "")
        insights_key = _cache_key("insights", province, "全部", "", "", 3)

        map_data = get_or_compute(
            map_key,
            lambda p=province: get_mysql_overview_map(p),
            allow_async=False,
        )
        insights = get_or_compute(
            insights_key,
            lambda p=province: get_mysql_city_insights(p, "全部", limit=3),
            allow_async=False,
        )
        regions = len((map_data or {}).get("regions") or [])
        if map_data and insights:
            ok += 1
            print(f"  OK {province}: {regions} 市", flush=True)
        else:
            print(f"  FAIL {province}", flush=True)

    print(f"预热完成：{ok}/{len(provinces)} 省", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
