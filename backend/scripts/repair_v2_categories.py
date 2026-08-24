#!/usr/bin/env python3
"""修正 v2 五表结构中误识别的 category 列（购进日期、OCR 残缺名等）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.analytics import resolve_category_from_mysql_row  # noqa: E402
from food_inspection.category_junk import is_junk_category  # noqa: E402
from food_inspection.db import connection  # noqa: E402
from food_inspection.mysql_v2 import create_compat_view  # noqa: E402


def _needs_repair(raw: str, resolved: str) -> bool:
    raw = (raw or "").strip()
    resolved = (resolved or "").strip() or "未分类"
    if raw == resolved:
        return False
    if is_junk_category(raw):
        return True
    return raw != resolved


def repair_categories(*, batch_size: int = 5000, dry_run: bool = False) -> int:
    scanned = 0
    updated_q = 0
    updated_u = 0
    affected_files: set[str] = set()
    last_id = 0

    with connection() as conn, conn.cursor() as cur:
        while True:
            cur.execute(
                """
                SELECT
                  b.id,
                  b.status,
                  b.file_source,
                  COALESCE(q.food_name, u.food_name) AS food_name,
                  COALESCE(q.category, u.category) AS category,
                  COALESCE(u.unqualified_item, '') AS unqualified_item,
                  COALESCE(u.standard_value, '') AS standard_value,
                  COALESCE(u.test_result, '') AS test_result
                FROM inspection_base b
                LEFT JOIN inspection_qualified q ON q.base_id = b.id
                LEFT JOIN inspection_unqualified u ON u.base_id = b.id
                WHERE b.id > %s
                ORDER BY b.id
                LIMIT %s
                """,
                (last_id, batch_size),
            )
            rows = cur.fetchall()
            if not rows:
                break

            q_updates: list[tuple[str, int]] = []
            u_updates: list[tuple[str, int]] = []
            for row in rows:
                scanned += 1
                last_id = int(row["id"])
                raw = (row["category"] or "").strip()
                reason = ""
                if row["standard_value"] or row["test_result"]:
                    reason = f"标准: {row['standard_value']}；实测: {row['test_result']}"
                resolved = resolve_category_from_mysql_row(
                    category=raw,
                    food_name=row["food_name"],
                    unqualified_item=row["unqualified_item"],
                    unqualified_reason=reason,
                    file_source=row["file_source"],
                )
                if not _needs_repair(raw, resolved):
                    continue
                affected_files.add(row["file_source"] or "")
                if row["status"] == "合格":
                    q_updates.append((resolved[:100], last_id))
                else:
                    u_updates.append((resolved[:100], last_id))

            if not dry_run:
                if q_updates:
                    cur.executemany(
                        "UPDATE inspection_qualified SET category = %s WHERE base_id = %s",
                        q_updates,
                    )
                    updated_q += len(q_updates)
                if u_updates:
                    cur.executemany(
                        "UPDATE inspection_unqualified SET category = %s WHERE base_id = %s",
                        u_updates,
                    )
                    updated_u += len(u_updates)
                conn.commit()
            else:
                updated_q += len(q_updates)
                updated_u += len(u_updates)

            print(f"已扫描 {scanned} 行，合格更新 {updated_q}，不合格更新 {updated_u}…", flush=True)

        if not dry_run:
            create_compat_view()

    print(f"涉及源文件 {len(affected_files)} 个")
    for path in sorted(affected_files)[:30]:
        print(f"  - {path}")
    if len(affected_files) > 30:
        print(f"  … 另有 {len(affected_files) - 30} 个")

    mode = "（预览）" if dry_run else ""
    print(f"完成{mode}：扫描 {scanned} 行，更新合格 {updated_q}、不合格 {updated_u}。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="修正 v2 表内误识别食品分类")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return repair_categories(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
