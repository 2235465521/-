"""用被抽样单位名称修复缓存中为空/占位符的公司名。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

import json
import os
import sys
from datetime import datetime

from food_inspection.parser import is_invalid_company, parse_file, record_to_dict

from config import CACHE_FILE, ROOT_DIR


def _count_bad(data: dict) -> int:
    return sum(
        1
        for key in ("qualified", "unqualified")
        for r in data.get(key, [])
        if is_invalid_company(r.get("company"))
    )


def _needs_company_repair(record: dict) -> bool:
    company = record.get("company") or ""
    if is_invalid_company(company):
        return True
    if "委托方" in company and "受托方" in company:
        return True
    path = record.get("source_file") or ""
    return "保健食品" in path


def repair_company_cache(data: dict) -> tuple[dict, int, int]:
    """重新解析公司名需修正的源文件（空名、委托方合并、保健食品表等）。"""
    bad_files: set[str] = set()
    for key in ("qualified", "unqualified"):
        for record in data.get(key, []):
            if _needs_company_repair(record):
                path = record.get("source_file") or ""
                if path:
                    bad_files.add(path)

    if not bad_files:
        return data, 0, 0

    reparsed: dict[str, list[dict]] = {}
    failed: list[str] = []
    for filepath in sorted(bad_files):
        try:
            records = parse_file(filepath)
            reparsed[filepath] = [record_to_dict(r) for r in records]
        except Exception:
            failed.append(filepath)

    removed = 0
    for key in ("qualified", "unqualified"):
        kept: list[dict] = []
        for record in data.get(key, []):
            path = record.get("source_file") or ""
            if path in reparsed:
                removed += 1
                continue
            kept.append(record)
        data[key] = kept

    added = 0
    for records in reparsed.values():
        for record in records:
            status = record.get("status")
            bucket = "qualified" if status == "qualified" else "unqualified"
            data.setdefault(bucket, []).append(record)
            added += 1

    scan_info = data.setdefault("scan_info", {})
    scan_info["company_repaired_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_info["company_repaired_files"] = len(reparsed)
    if failed:
        scan_info["company_repair_failed_files"] = failed

    return data, added, removed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.path.isfile(CACHE_FILE):
        print("未找到 data_cache.json")
        sys.exit(1)

    with open(CACHE_FILE, encoding="utf-8") as f:
        data = json.load(f)

    before = _count_bad(data)

    data, added, removed = repair_company_cache(data)

    after = _count_bad(data)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"修复前空公司名: {before} 条")
    print(f"重新解析替换: {removed} 条，写回: {added} 条")
    print(f"修复后空公司名: {after} 条（已用被抽样单位名称回填 {before - after} 条）")
    print(f"已保存: {CACHE_FILE}")


if __name__ == "__main__":
    main()
