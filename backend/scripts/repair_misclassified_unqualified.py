"""将误标为不合格（无不合格项目/原因）的记录移回合格，并重建统计。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

import json
import os
import sys
from datetime import datetime

from food_inspection.scan import rebuild_province_stats

from config import CACHE_FILE, ROOT_DIR


def _should_be_qualified(rec: dict) -> bool:
    item = (rec.get("unqualified_item") or "").strip()
    reason = (rec.get("reason") or "").strip()
    if item:
        return False
    if reason and any(k in reason for k in ("不合格", "超标", "检出", "不得")):
        return False
    return True


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE_FILE, encoding="utf-8") as f:
        data = json.load(f)

    qualified = list(data.get("qualified", []))
    unqualified = list(data.get("unqualified", []))
    before_u = len(unqualified)

    kept_u: list[dict] = []
    moved: list[dict] = []
    for rec in unqualified:
        if _should_be_qualified(rec):
            rec = dict(rec)
            rec["status"] = "qualified"
            rec["unqualified_item"] = ""
            rec["reason"] = ""
            moved.append(rec)
        else:
            kept_u.append(rec)

    qualified.extend(moved)
    data["qualified"] = qualified
    data["unqualified"] = kept_u

    stats = data.setdefault("stats", {})
    stats["qualified_count"] = len(qualified)
    stats["unqualified_count"] = len(kept_u)
    parsed_paths = {
        rec.get("source_file")
        for rec in qualified + kept_u
        if rec.get("source_file")
    }
    stats["parsed_files"] = len(parsed_paths)
    stats["provinces"] = rebuild_province_stats(qualified, kept_u)

    info = data.setdefault("scan_info", {})
    info["repaired_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info["repaired_moved_to_qualified"] = len(moved)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"不合格记录: {before_u} -> {len(kept_u)}")
    print(f"移回合格: {len(moved)}")
    print(f"合格记录: {len(qualified)}")
    print(f"已保存: {CACHE_FILE}")


if __name__ == "__main__":
    main()
