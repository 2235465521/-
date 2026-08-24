#!/usr/bin/env python3
"""删除误标为合格的核查处置/风险控制正文记录。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.db import connection  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE b FROM inspection_base b
            WHERE b.status = '合格'
              AND (
                b.file_source LIKE '%核查处置%'
                OR b.file_source LIKE '%风险控制%'
              )
              AND b.file_source LIKE '%_正文%'
            """
        )
        deleted = cur.rowcount
        conn.commit()
    print(f"已删除误标合格记录: {deleted} 条")


if __name__ == "__main__":
    main()
