#!/usr/bin/env python3
"""为 analytics 磁盘缓存写入 product_batch_totals，避免接口实时全表聚合。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts._bootstrap  # noqa: F401

from config import ROOT_DIR
from food_inspection.analytics import (
    _apply_repeat_product_batch_totals,
    _merge_repeat_product_rows,
    refresh_analytics_failure_names,
)
from food_inspection.db import fetch_product_batch_totals_for_names


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cache_dir = Path(ROOT_DIR) / "data" / "analytics_disk_cache"
    if not cache_dir.is_dir():
        print("无 analytics 缓存目录")
        return

    for path in sorted(cache_dir.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("loading"):
            continue
        if data.get("product_batch_totals"):
            print(f"跳过（已有）: {path.name}")
            continue

        province = data.get("province") or "全部"
        city = data.get("city") or "全部"
        date_from = data.get("date_from") or None
        date_to = data.get("date_to") or None
        print(f"预热 {path.name} ({province}/{city}) ...", flush=True)
        repeat_names = [
            str(row.get("product") or "").strip()
            for row in data.get("repeat_products") or []
            if row.get("product")
        ]
        batch_map = fetch_product_batch_totals_for_names(
            repeat_names,
            province=province,
            city=city,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        repeat_only = {
            row["product"]: batch_map[row["product"]]
            for row in data.get("repeat_products") or []
            if row.get("product") in batch_map
        }
        data["product_batch_totals"] = repeat_only
        for row in data.get("repeat_products") or []:
            _apply_repeat_product_batch_totals(row, batch_map)
        data = refresh_analytics_failure_names(data)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        banana = next(
            (r for r in data.get("repeat_products") or [] if r.get("product") == "香蕉"),
            None,
        )
        if banana:
            print(
                f"  香蕉: 违规 {banana.get('count')} / 总数 {banana.get('total_count')}",
                flush=True,
            )
        print(f"  已写入 {len(repeat_only)} 个产品抽检总数", flush=True)


if __name__ == "__main__":
    main()
