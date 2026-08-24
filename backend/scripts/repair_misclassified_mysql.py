"""将 MySQL 中无不合格项目/检测值的误标不合格记录移回合格。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.db import connection  # noqa: E402


def _select_misclassified_ids(cur) -> list[int]:
    cur.execute(
        """
        SELECT b.id, u.food_name, u.category
        FROM inspection_base b
        INNER JOIN inspection_unqualified u ON u.base_id = b.id
        LEFT JOIN inspection_qualified q ON q.base_id = b.id
        WHERE b.status = '不合格'
          AND q.base_id IS NULL
          AND TRIM(COALESCE(u.unqualified_item, '')) = ''
          AND TRIM(COALESCE(u.standard_value, '')) = ''
          AND TRIM(COALESCE(u.test_result, '')) = ''
        """
    )
    return [(row["id"], row["food_name"], row["category"]) for row in cur.fetchall()]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with connection() as conn, conn.cursor() as cur:
        rows = _select_misclassified_ids(cur)
        if not rows:
            print("无需修复的记录")
            return

        moved = 0
        for base_id, food_name, category in rows:
            cur.execute(
                "UPDATE inspection_base SET status = '合格' WHERE id = %s",
                (base_id,),
            )
            cur.execute(
                """
                INSERT INTO inspection_qualified (base_id, result_label, food_name, category)
                VALUES (%s, '合格', %s, %s)
                """,
                (base_id, food_name or "", category or ""),
            )
            cur.execute(
                "DELETE FROM inspection_unqualified WHERE base_id = %s",
                (base_id,),
            )
            moved += 1

        conn.commit()
        print(f"已移回合格: {moved} 条")


if __name__ == "__main__":
    main()
