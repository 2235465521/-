#!/usr/bin/env python3
"""重导陕西省「合格附件」中误读 Sheet1 旧不合格表的历史数据。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT  # noqa: E402
from food_inspection.db import connection, resolve_disk_path  # noqa: E402
from food_inspection.mysql_v2 import create_compat_view, insert_records_batch  # noqa: E402
from food_inspection.parser import parse_file  # noqa: E402
from food_inspection.store import invalidate_analytics_cache  # noqa: E402

_BATCH = 500
_PROVINCE = "陕西省"


def _phantom_file_sources() -> list[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT file_source
            FROM inspection_base
            WHERE province = %s
              AND status = '不合格'
              AND source_sheet = 'Sheet1'
              AND (file_source LIKE %s OR file_source LIKE %s)
            ORDER BY file_source
            """,
            (_PROVINCE, "%合格%", "%合 格%"),
        )
        return [str(row["file_source"]) for row in cur.fetchall()]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    dry_run = "--dry-run" in sys.argv
    rel_keys = _phantom_file_sources()
    print(f"待重导合格附件（含 Sheet1 残留不合格）: {len(rel_keys)} 个")
    if not rel_keys:
        return 0

    deleted = 0
    imported = 0
    qualified = 0
    unqualified = 0
    missing = 0
    failed: list[str] = []

    with connection() as conn, conn.cursor() as cur:
        if dry_run:
            cur.execute(
                "SELECT COUNT(*) AS n FROM inspection_base WHERE file_source IN %s",
                (tuple(rel_keys),),
            )
            deleted = int(cur.fetchone()["n"])
        else:
            for rel in rel_keys:
                cur.execute("DELETE FROM inspection_base WHERE file_source = %s", (rel,))
                deleted += cur.rowcount
            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
            next_id = int(cur.fetchone()["n"])

        pending: list = []
        for rel in rel_keys:
            disk = resolve_disk_path(rel)
            if not disk or not Path(disk).is_file():
                missing += 1
                continue
            try:
                records = parse_file(disk)
            except Exception as exc:
                failed.append(f"{rel}\t{exc}")
                continue
            for record in records:
                if dry_run:
                    imported += 1
                    if record.status == "qualified":
                        qualified += 1
                    else:
                        unqualified += 1
                    continue
                pending.append((record, next_id))
                next_id += 1
                imported += 1
                if record.status == "qualified":
                    qualified += 1
                else:
                    unqualified += 1
                if len(pending) >= _BATCH:
                    insert_records_batch(cur, pending)
                    pending.clear()

        if not dry_run:
            if pending:
                insert_records_batch(cur, pending)
            conn.commit()
            create_compat_view()
            invalidate_analytics_cache()

    print(f"删除旧记录: {deleted}")
    print(f"重新导入: {imported}（合格 {qualified}，不合格 {unqualified}）")
    if missing:
        print(f"磁盘缺失: {missing} 个")
    if failed:
        print(f"解析失败: {len(failed)} 个")
        for line in failed[:5]:
            print(" ", line)
    if dry_run:
        print("（dry-run，未写入）")
    else:
        print("已刷新 analytics 缓存标记")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
