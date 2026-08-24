#!/usr/bin/env python3
"""删除无效单位名（公司名残片）相关记录。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.db import connection  # noqa: E402
from food_inspection.parser.text import is_invalid_company  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.id, c.sampled_company, c.manufacturer
            FROM inspection_base b
            JOIN inspection_company c ON c.base_id = b.id
            """
        )
        remove_ids: list[int] = []
        for row in cur.fetchall():
            sampled = (row.get("sampled_company") or "").strip()
            manufacturer = (row.get("manufacturer") or "").strip()
            if is_invalid_company(sampled) or is_invalid_company(manufacturer):
                remove_ids.append(int(row["id"]))

        if not remove_ids:
            print("无需清理")
            return

        chunk = 500
        deleted = 0
        for i in range(0, len(remove_ids), chunk):
            part = remove_ids[i : i + chunk]
            placeholders = ",".join(["%s"] * len(part))
            cur.execute(f"DELETE FROM inspection_base WHERE id IN ({placeholders})", part)
            deleted += cur.rowcount
        conn.commit()
    print(f"已删除无效单位记录: {deleted} 条")


if __name__ == "__main__":
    main()
