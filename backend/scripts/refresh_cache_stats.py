"""仅刷新缓存中的文件统计（不重新解析），应用非明细附件排除规则。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, ROOT_DIR

import json
import os
import sys
from datetime import datetime

from food_inspection.analytics import count_qualified_items, count_unqualified_items
from food_inspection.scan import (
    _filter_stat_file_paths,
    count_skipped_files,
    rebuild_province_stats,
)

CACHE = CACHE_FILE


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE, encoding="utf-8") as f:
        data = json.load(f)

    qualified = data.get("qualified", [])
    unqualified = data.get("unqualified", [])
    total, skipped_planned, skipped_non_detail = count_skipped_files()
    effective_total = total - skipped_planned - skipped_non_detail

    parsed_paths = {
        rec.get("source_file")
        for rec in qualified + unqualified
        if rec.get("source_file")
    }
    parsed_files = len(parsed_paths)

    scan_info = data.setdefault("scan_info", {})
    scan_info["empty_file_paths"] = _filter_stat_file_paths(
        scan_info.get("empty_file_paths", [])
    )
    scan_info["failed_file_paths"] = _filter_stat_file_paths(
        scan_info.get("failed_file_paths", [])
    )
    scan_info["stats_refreshed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats = data.setdefault("stats", {})
    stats.update(
        {
            "qualified_count": count_qualified_items(qualified),
            "unqualified_count": count_unqualified_items(unqualified),
            "total_files": effective_total,
            "parsed_files": parsed_files,
            "skipped_planned_files": skipped_planned,
            "skipped_non_detail_files": skipped_non_detail,
            "empty_files": max(
                effective_total - parsed_files - len(scan_info.get("failed_file_paths", [])),
                0,
            ),
            "failed_files": len(scan_info.get("failed_file_paths", [])),
            "provinces": rebuild_province_stats(qualified, unqualified),
        }
    )

    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"有效文件: {parsed_files}/{effective_total}")
    print(f"计划清单(排除): {skipped_planned}")
    print(f"非明细附件(排除): {skipped_non_detail}")
    print(f"空文件列表已清理: 剩余 {len(scan_info['empty_file_paths'])} 条")
    print(f"已保存: {CACHE}")


if __name__ == "__main__":
    main()
