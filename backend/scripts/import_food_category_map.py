#!/usr/bin/env python3
"""从 Excel 导入食品原名 → 大类/小类 映射到 dim_food_category_map。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401

_SCHEMA = BACKEND_DIR / "sql" / "food_category_schema.sql"


def _ensure_schema(conn) -> None:
    sql = _SCHEMA.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        for chunk in sql.split(";"):
            statement = chunk.strip()
            if not statement or statement.startswith("--"):
                continue
            if statement.upper().startswith("USE "):
                continue
            cur.execute(statement)
    conn.commit()


def import_excel(excel_path: Path, *, truncate: bool = True) -> dict[str, int]:
    import pandas as pd
    from food_inspection.db import connection
    from food_inspection.food_category_map import invalidate_map_cache

    df = pd.read_excel(
        excel_path,
        usecols=["food_name", "大类", "小类", "标准品名", "记录数", "分类来源", "置信度"],
    )
    df = df.fillna("")
    rows: list[tuple] = []
    for _, row in df.iterrows():
        original = str(row["food_name"] or "").strip()
        if not original:
            continue
        rows.append(
            (
                original,
                str(row["大类"] or "").strip()[:100],
                str(row["小类"] or "").strip()[:128],
                str(row["标准品名"] or "").strip()[:128],
                str(row["分类来源"] or "").strip()[:32],
                str(row["置信度"] or "").strip()[:16],
                int(row["记录数"] or 0),
            )
        )

    with connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            if truncate:
                cur.execute("TRUNCATE TABLE dim_food_category_map")
            batch = 2000
            for i in range(0, len(rows), batch):
                cur.executemany(
                    """
                    INSERT INTO dim_food_category_map (
                      food_name_original, category_major, category_minor,
                      standard_name, map_source, confidence, record_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      category_major = VALUES(category_major),
                      category_minor = VALUES(category_minor),
                      standard_name = VALUES(standard_name),
                      map_source = VALUES(map_source),
                      confidence = VALUES(confidence),
                      record_count = VALUES(record_count)
                    """,
                    rows[i : i + batch],
                )
        conn.commit()

    invalidate_map_cache()
    return {"imported": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description="导入食品分类映射表")
    parser.add_argument(
        "excel",
        nargs="?",
        default=str(BACKEND_DIR.parent / "分类明细映射表_API全量(3).xlsx"),
        help="映射 Excel 路径",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="不清空维表，仅 upsert",
    )
    args = parser.parse_args()
    path = Path(args.excel)
    if not path.is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    stats = import_excel(path, truncate=not args.no_truncate)
    print(f"已导入 dim_food_category_map：{stats['imported']:,} 行", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
