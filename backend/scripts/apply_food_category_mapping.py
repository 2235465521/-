#!/usr/bin/env python3
"""按 dim_food_category_map 回填 inspection 表大类/小类；未映射行清空且不纳入统计。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401


def apply_mapping(*, dry_run: bool = True) -> dict[str, int]:
    from food_inspection.db import connection
    from food_inspection.food_category_map import invalidate_map_cache
    from food_inspection.mysql_v2 import create_compat_view

    stats = {
        "qualified_mapped": 0,
        "qualified_cleared": 0,
        "unqualified_mapped": 0,
        "unqualified_cleared": 0,
    }

    with connection() as conn, conn.cursor() as cur:
        if dry_run:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM inspection_qualified q
                INNER JOIN dim_food_category_map m
                  ON TRIM(q.food_name) = m.food_name_original
                WHERE TRIM(m.category_minor) <> ''
                """
            )
            stats["qualified_mapped"] = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM inspection_qualified q
                LEFT JOIN dim_food_category_map m
                  ON TRIM(q.food_name) = m.food_name_original
                WHERE m.food_name_original IS NULL
                """
            )
            stats["qualified_cleared"] = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM inspection_unqualified u
                INNER JOIN dim_food_category_map m
                  ON TRIM(u.food_name) = m.food_name_original
                WHERE TRIM(m.category_minor) <> ''
                """
            )
            stats["unqualified_mapped"] = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM inspection_unqualified u
                LEFT JOIN dim_food_category_map m
                  ON TRIM(u.food_name) = m.food_name_original
                WHERE m.food_name_original IS NULL
                """
            )
            stats["unqualified_cleared"] = int(cur.fetchone()["n"])
            return stats

        cur.execute(
            """
            UPDATE inspection_qualified q
            INNER JOIN dim_food_category_map m
              ON TRIM(q.food_name) = m.food_name_original
            SET q.category = m.category_major,
                q.sub_category = m.category_minor
            WHERE TRIM(m.category_minor) <> ''
            """
        )
        stats["qualified_mapped"] = int(cur.rowcount or 0)

        cur.execute(
            """
            UPDATE inspection_qualified q
            LEFT JOIN dim_food_category_map m
              ON TRIM(q.food_name) = m.food_name_original
            SET q.category = '', q.sub_category = ''
            WHERE m.food_name_original IS NULL
            """
        )
        stats["qualified_cleared"] = int(cur.rowcount or 0)

        cur.execute(
            """
            UPDATE inspection_unqualified u
            INNER JOIN dim_food_category_map m
              ON TRIM(u.food_name) = m.food_name_original
            SET u.category = m.category_major,
                u.sub_category = m.category_minor
            WHERE TRIM(m.category_minor) <> ''
            """
        )
        stats["unqualified_mapped"] = int(cur.rowcount or 0)

        cur.execute(
            """
            UPDATE inspection_unqualified u
            LEFT JOIN dim_food_category_map m
              ON TRIM(u.food_name) = m.food_name_original
            SET u.category = '', u.sub_category = ''
            WHERE m.food_name_original IS NULL
            """
        )
        stats["unqualified_cleared"] = int(cur.rowcount or 0)
        conn.commit()

    create_compat_view()
    invalidate_map_cache()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="回填食品大类/小类")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认仅预览）")
    args = parser.parse_args()
    stats = apply_mapping(dry_run=not args.apply)
    mode = "预览" if not args.apply else "已应用"
    print(
        f"{mode}：合格映射 {stats['qualified_mapped']:,}，合格清空 {stats['qualified_cleared']:,}；"
        f"不合格映射 {stats['unqualified_mapped']:,}，不合格清空 {stats['unqualified_cleared']:,}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
