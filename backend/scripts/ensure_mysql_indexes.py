#!/usr/bin/env python3
"""确保 inspection_base 列表查询索引存在。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401

INDEX_STATEMENTS = [
    (
        "idx_base_status_year_id",
        "ALTER TABLE inspection_base "
        "ADD INDEX idx_base_status_year_id (status, year, id)",
    ),
    (
        "idx_base_status_province_city_year_id",
        "ALTER TABLE inspection_base "
        "ADD INDEX idx_base_status_province_city_year_id (status, province, city, year, id)",
    ),
]


def _has_index(cur, table: str, index_name: str) -> bool:
    cur.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", (index_name,))
    return bool(cur.fetchone())


def main() -> int:
    from food_inspection.db import connection

    applied = 0
    with connection() as conn, conn.cursor() as cur:
        for index_name, ddl in INDEX_STATEMENTS:
            if _has_index(cur, "inspection_base", index_name):
                print(f"  skip {index_name} (exists)", flush=True)
                continue
            try:
                cur.execute(ddl)
                conn.commit()
                applied += 1
                print(f"  added {index_name}", flush=True)
            except Exception as exc:
                print(f"  fail {index_name}: {exc}", flush=True)
    print(f"索引检查完成，新增 {applied} 个", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
