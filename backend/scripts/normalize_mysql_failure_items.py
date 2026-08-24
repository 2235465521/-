#!/usr/bin/env python3
"""批量修正 MySQL 不合格项目字段：从 reason / project_details 回填并归一化 OCR 别名。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import MYSQL_TABLE, MYSQL_URL  # noqa: E402
from food_inspection.db import row_to_record  # noqa: E402
from food_inspection.parser.fields import (  # noqa: E402
    _compact_failure_item_text,
    _item_field_is_usable,
    normalize_failure_item_name,
    resolve_record_unqualified_item,
)

_SKIP_VERDICT = frozenset({"合格", "不合格", "不符合", "未标注"})


def _resolved_item(row: dict) -> str:
    record = row_to_record(row)
    name = resolve_record_unqualified_item(record)
    return normalize_failure_item_name(name) if name else ""


def _needs_item_update(current: str, resolved: str) -> bool:
    if not resolved:
        return False
    raw = (current or "").strip()
    if not raw:
        return True
    if not _item_field_is_usable(raw, _SKIP_VERDICT):
        return True
    current_norm = normalize_failure_item_name(raw)
    if not current_norm:
        return True
    if current_norm != resolved:
        return True
    if _compact_failure_item_text(raw) == resolved and raw != resolved:
        return True
    return False


def _needs_reason_backfill(row: dict) -> str | None:
    reason = (row.get("unqualified_reason") or "").strip()
    if reason:
        return None
    details = (row.get("unqualified_project_details") or "").strip()
    if not details:
        return None
    return details


def main() -> int:
    parser = argparse.ArgumentParser(description="归一化 shipin 表内不合格项目字段")
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not MYSQL_URL:
        print("未配置 MYSQL_URL", file=sys.stderr)
        return 1

    from food_inspection.db import connection

    table = MYSQL_TABLE
    scanned = 0
    item_updates = 0
    reason_updates = 0
    last_id = 0

    select_sql = f"""
        SELECT
            id, status, province, city, county, year, file_source, source_sheet,
            sampled_company_name, manufacturer_name, food_name, category,
            unqualified_item, unqualified_reason, unqualified_project_details
        FROM `{table}`
        WHERE status = 'unqualified' AND id > %s
        ORDER BY id
        LIMIT %s
    """
    item_update_sql = f"UPDATE `{table}` SET unqualified_item = %s WHERE id = %s"
    reason_update_sql = (
        f"UPDATE `{table}` SET unqualified_reason = %s "
        f"WHERE id = %s AND (unqualified_reason IS NULL OR TRIM(unqualified_reason) = '')"
    )

    with connection() as conn, conn.cursor() as cur:
        while True:
            cur.execute(select_sql, (last_id, args.batch_size))
            rows = cur.fetchall()
            if not rows:
                break

            item_batch: list[tuple[str, int]] = []
            reason_batch: list[tuple[str, int]] = []

            for row in rows:
                scanned += 1
                last_id = int(row["id"])
                resolved = _resolved_item(row)
                current = row.get("unqualified_item") or ""

                if _needs_item_update(current, resolved):
                    item_batch.append((resolved, last_id))
                    item_updates += 1

                backfill = _needs_reason_backfill(row)
                if backfill:
                    reason_batch.append((backfill, last_id))
                    reason_updates += 1

            if not args.dry_run:
                if item_batch:
                    cur.executemany(item_update_sql, item_batch)
                if reason_batch:
                    cur.executemany(reason_update_sql, reason_batch)

            print(
                f"已扫描 {scanned} 行，项目更新 {item_updates}，reason 回填 {reason_updates}…",
                flush=True,
            )

    mode = "（预览）" if args.dry_run else ""
    print(
        f"完成{mode}：扫描 {scanned} 行不合格记录，"
        f"更新 unqualified_item {item_updates} 行，回填 unqualified_reason {reason_updates} 行。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
