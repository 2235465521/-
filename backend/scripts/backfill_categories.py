#!/usr/bin/env python3
"""按产品名/路径推断结果，回写 inspection_qualified / inspection_unqualified 的 category。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.analytics import resolve_category_from_mysql_row  # noqa: E402
from food_inspection.db import connection  # noqa: E402

_BATCH = 500
_VAGUE = (
    "食品相关产品",
    "工业加工食品",
    "餐饮加工食品",
    "其他食品",
)


def backfill_categories(*, all_rows: bool = False) -> int:
    updated_q = 0
    updated_u = 0
    scanned = 0

    with connection() as conn, conn.cursor() as cur:
        cats = ", ".join(f"'{c}'" for c in _VAGUE)
        where = f"category IN ({cats})"

        cur.execute(
            f"""
            SELECT base_id, food_name, category, '' AS unqualified_item, '' AS test_result,
                   '' AS standard_value, b.file_source
            FROM inspection_qualified q
            JOIN inspection_base b ON b.id = q.base_id
            WHERE {where}
            """
        )
        q_rows = cur.fetchall()

        u_where = where.replace("category", "u.category")
        cur.execute(
            f"""
            SELECT u.base_id, u.food_name, u.category, u.unqualified_item, u.test_result,
                   u.standard_value, b.file_source
            FROM inspection_unqualified u
            JOIN inspection_base b ON b.id = u.base_id
            WHERE {u_where}
            """
        )
        u_rows = cur.fetchall()

        pending_q: list[tuple[str, int]] = []
        pending_u: list[tuple[str, int]] = []

        for row in q_rows:
            scanned += 1
            old = (row["category"] or "").strip()
            reason = ""
            new = resolve_category_from_mysql_row(
                category=old,
                food_name=(row["food_name"] or "").strip(),
                unqualified_item="",
                unqualified_reason=reason,
                file_source=(row["file_source"] or "").strip(),
            )
            if new != old:
                pending_q.append((new, int(row["base_id"])))
                updated_q += 1
            if len(pending_q) >= _BATCH:
                cur.executemany(
                    "UPDATE inspection_qualified SET category = %s WHERE base_id = %s",
                    pending_q,
                )
                pending_q.clear()

        for row in u_rows:
            scanned += 1
            old = (row["category"] or "").strip()
            measured = (row["test_result"] or "").strip()
            standard = (row["standard_value"] or "").strip()
            reason = f"标准: {standard}；实测: {measured}" if standard or measured else ""
            new = resolve_category_from_mysql_row(
                category=old,
                food_name=(row["food_name"] or "").strip(),
                unqualified_item=(row["unqualified_item"] or "").strip(),
                unqualified_reason=reason,
                file_source=(row["file_source"] or "").strip(),
            )
            if new != old:
                pending_u.append((new, int(row["base_id"])))
                updated_u += 1
            if len(pending_u) >= _BATCH:
                cur.executemany(
                    "UPDATE inspection_unqualified SET category = %s WHERE base_id = %s",
                    pending_u,
                )
                pending_u.clear()

        if pending_q:
            cur.executemany(
                "UPDATE inspection_qualified SET category = %s WHERE base_id = %s",
                pending_q,
            )
        if pending_u:
            cur.executemany(
                "UPDATE inspection_unqualified SET category = %s WHERE base_id = %s",
                pending_u,
            )

    print(
        f"扫描 {scanned} 条，更新合格 {updated_q} 条，更新不合格 {updated_u} 条",
        flush=True,
    )
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="回写食品大类 category")
    parser.add_argument("--all", action="store_true", help="全表扫描（较慢）")
    args = parser.parse_args()
    return backfill_categories(all_rows=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
