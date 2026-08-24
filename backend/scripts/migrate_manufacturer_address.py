#!/usr/bin/env python3
"""为 inspection_address 增加生产企业地址列，并刷新兼容视图。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.db import connection  # noqa: E402
from food_inspection.mysql_v2 import create_compat_view  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'inspection_address'
              AND COLUMN_NAME = 'manufacturer_address'
            """
        )
        exists = int(cur.fetchone()["c"])
        if not exists:
            cur.execute(
                """
                ALTER TABLE inspection_address
                ADD COLUMN manufacturer_address TEXT NULL COMMENT '生产企业地址'
                AFTER address
                """
            )
            print("已添加 inspection_address.manufacturer_address")
        else:
            print("列 manufacturer_address 已存在，跳过 ALTER")

    create_compat_view()
    print("已刷新 food_inspection_records 视图")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
