#!/usr/bin/env python3
"""按产品名/路径推断结果，批量修正 MySQL 中的 category 列。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import MYSQL_TABLE, MYSQL_URL  # noqa: E402
from food_inspection.analytics import resolve_category_from_mysql_row  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="归一化 shipin 表内食品分类")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not MYSQL_URL:
        print("未配置 MYSQL_URL", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine, text

    engine = create_engine(MYSQL_URL, pool_pre_ping=True)
    table = MYSQL_TABLE
    updated = 0
    scanned = 0
    last_id = 0

    with engine.connect() as conn:
        while True:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, category, food_name, unqualified_item, unqualified_reason, file_source
                    FROM `{table}`
                    WHERE id > :last_id
                    ORDER BY id
                    LIMIT :limit
                    """
                ),
                {"last_id": last_id, "limit": args.batch_size},
            ).fetchall()
            if not rows:
                break

            batch_updates: list[dict[str, object]] = []
            for row in rows:
                scanned += 1
                last_id = int(row[0])
                raw = (row[1] or "").strip()
                resolved = resolve_category_from_mysql_row(
                    category=row[1],
                    food_name=row[2],
                    unqualified_item=row[3],
                    unqualified_reason=row[4],
                    file_source=row[5],
                )
                if resolved and resolved != raw:
                    batch_updates.append({"id": last_id, "category": resolved})
                    updated += 1

            if batch_updates and not args.dry_run:
                stmt = text(f"UPDATE `{table}` SET category = :category WHERE id = :id")
                for item in batch_updates:
                    conn.execute(stmt, item)
                conn.commit()

            print(f"已扫描 {scanned} 行，待更新 {updated} 行…", flush=True)

    mode = "（预览）" if args.dry_run else ""
    print(f"完成{mode}：扫描 {scanned} 行，更新 {updated} 行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
