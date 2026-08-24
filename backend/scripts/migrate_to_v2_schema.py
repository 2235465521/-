#!/usr/bin/env python3
"""将 food_inspection_records 宽表迁移为五表结构，并创建兼容视图。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import MYSQL_DATABASE, MYSQL_TABLE  # noqa: E402
from food_inspection.db import connection, row_to_record  # noqa: E402
from food_inspection.parser.fields import (  # noqa: E402
    _split_combined_failure,
    normalize_failure_item_name,
    resolve_record_unqualified_item,
)

_YEAR_RE = re.compile(r"^20\d{2}$")
_LEGACY_TABLE = f"{MYSQL_TABLE}_legacy"
_SCHEMA_FILE = BACKEND_DIR / "sql" / "inspection_schema_v2.sql"


def _normalize_location(row: dict) -> tuple[str, str, str, str]:
    province = (row.get("province") or "").strip()
    city = (row.get("city") or "").strip()
    county = (row.get("county") or "").strip()
    year = (row.get("year") or "").strip()

    if _YEAR_RE.fullmatch(city):
        if not year:
            year = city
        city = county if county and not _YEAR_RE.fullmatch(county) else ""
        county = ""

    if not year:
        match = _YEAR_RE.search((row.get("file_source") or "").replace("\\", "/"))
        if match:
            year = match.group(0)

    return province, city, year, county


def _build_region(province: str, city: str, county: str) -> str:
    parts: list[str] = []
    for part in (province, city, county):
        part = (part or "").strip()
        if not part or _YEAR_RE.fullmatch(part) or part in parts:
            continue
        parts.append(part)
    return "".join(parts)


def _extract_test_standard(row: dict) -> tuple[str, str, str]:
    reason = (row.get("unqualified_reason") or "").strip()
    details = (row.get("unqualified_project_details") or "").strip()
    text = reason or details

    item = normalize_failure_item_name(row.get("unqualified_item") or "")
    if not item:
        item = resolve_record_unqualified_item(row_to_record(row))

    standard = ""
    measured = ""

    std_match = re.search(r"标准[:：]\s*([^；;|║‖\n]+)", text)
    if std_match:
        standard = std_match.group(1).strip()

    meas_match = re.search(r"实测[:：]\s*([^（(\n]+)", text)
    if meas_match:
        segment = meas_match.group(1).strip()
        _, meas_part, std_part = _split_combined_failure(segment)
        if meas_part:
            measured = meas_part
        if std_part and not standard:
            standard = std_part
        if not measured:
            for sep in ("║", "‖", "||", "|"):
                if sep in segment:
                    parts = [p.strip() for p in segment.split(sep) if p.strip()]
                    if len(parts) >= 2:
                        measured = parts[1]
                    break

    if not measured or not standard:
        _, meas2, std2 = _split_combined_failure(details or reason)
        if meas2 and not measured:
            measured = meas2
        if std2 and not standard:
            standard = std2

    return item, measured[:255], standard[:255]


def _table_exists(cur, name: str) -> bool:
    cur.execute(
        """
        SELECT TABLE_TYPE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (MYSQL_DATABASE, name),
    )
    row = cur.fetchone()
    return bool(row)


def _is_base_table(cur, name: str) -> bool:
    cur.execute(
        """
        SELECT TABLE_TYPE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (MYSQL_DATABASE, name),
    )
    row = cur.fetchone()
    return bool(row and row["TABLE_TYPE"] == "BASE TABLE")


def _run_schema(cur, *, with_view: bool) -> None:
    sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    if not with_view:
        sql = sql.split("DROP VIEW IF EXISTS food_inspection_records", 1)[0]
    for stmt in sql.split(";"):
        chunk = stmt.strip()
        if not chunk or chunk.startswith("--"):
            continue
        cur.execute(chunk)


def _create_compat_view(cur) -> None:
    view_sql = """
    CREATE OR REPLACE VIEW food_inspection_records AS
    SELECT
      b.id AS id,
      CASE b.status WHEN '合格' THEN 'qualified' WHEN '不合格' THEN 'unqualified' ELSE b.status END AS status,
      b.province AS province,
      b.city AS city,
      '' AS county,
      b.year AS year,
      b.file_source AS file_source,
      b.source_sheet AS source_sheet,
      b.batch_serial AS serial_number,
      c.manufacturer AS manufacturer_name,
      a.address AS manufacturer_address,
      c.sampled_company AS sampled_company_name,
      a.address AS sampled_company_address,
      COALESCE(q.food_name, u.food_name) AS food_name,
      '/' AS specification,
      '/' AS trademark,
      NULL AS production_date_raw,
      CONCAT(
        COALESCE(u.unqualified_item, ''),
        CASE
          WHEN u.standard_value <> '' OR u.test_result <> ''
            THEN CONCAT('；标准: ', u.standard_value, '；实测: ', u.test_result)
          ELSE ''
        END
      ) AS unqualified_project_details,
      COALESCE(u.unqualified_item, '') AS unqualified_item,
      CASE
        WHEN u.standard_value <> '' OR u.test_result <> ''
          THEN CONCAT('标准: ', u.standard_value, '；实测: ', u.test_result)
        ELSE ''
      END AS unqualified_reason,
      COALESCE(q.category, u.category) AS category,
      '' AS remarks,
      b.created_at AS created_at
    FROM inspection_base b
    LEFT JOIN inspection_company c ON c.base_id = b.id
    LEFT JOIN inspection_address a ON a.base_id = b.id
    LEFT JOIN inspection_qualified q ON q.base_id = b.id
    LEFT JOIN inspection_unqualified u ON u.base_id = b.id
    """
    cur.execute("DROP VIEW IF EXISTS food_inspection_records")
    cur.execute(view_sql)


def migrate(*, batch_size: int = 3000, dry_run: bool = False) -> int:
    source_table = MYSQL_TABLE

    with connection() as conn, conn.cursor() as cur:
        if _is_base_table(cur, MYSQL_TABLE):
            if dry_run:
                cur.execute(f"SELECT COUNT(*) AS c FROM `{MYSQL_TABLE}`")
                total = int(cur.fetchone()["c"])
                print(f"（预览）将从 {MYSQL_TABLE} 迁移 {total} 行到五表结构")
                return 0
            print(f"备份旧表 {MYSQL_TABLE} → {_LEGACY_TABLE}")
            cur.execute(f"DROP TABLE IF EXISTS `{_LEGACY_TABLE}`")
            cur.execute(f"RENAME TABLE `{MYSQL_TABLE}` TO `{_LEGACY_TABLE}`")
            source_table = _LEGACY_TABLE
        elif _table_exists(cur, _LEGACY_TABLE):
            source_table = _LEGACY_TABLE
            print(f"使用已有备份表 {_LEGACY_TABLE}")
        elif _table_exists(cur, "inspection_base"):
            cur.execute("SELECT COUNT(*) AS c FROM inspection_base")
            existing = int(cur.fetchone()["c"])
            if existing > 0:
                print(f"五表结构已存在（{existing} 行），跳过迁移")
                _create_compat_view(cur)
                return 0
            source_table = _LEGACY_TABLE if _table_exists(cur, _LEGACY_TABLE) else MYSQL_TABLE
        elif not _table_exists(cur, "inspection_base"):
            print(f"错误：找不到源表 {MYSQL_TABLE} 或 {_LEGACY_TABLE}", file=sys.stderr)
            return 1

        if dry_run:
            cur.execute(f"SELECT COUNT(*) AS c FROM `{source_table}`")
            total = int(cur.fetchone()["c"])
            print(f"（预览）将迁移 {total} 行到五表结构")
            return 0

        print("创建五表结构…")
        _run_schema(cur, with_view=False)

        cur.execute(f"SELECT COUNT(*) AS c FROM `{source_table}`")
        total = int(cur.fetchone()["c"])
        print(f"开始迁移 {total} 行…")

        last_id = 0
        migrated = 0
        qualified_n = 0
        unqualified_n = 0

        insert_base = """
            INSERT INTO inspection_base
              (id, province, city, year, status, batch_serial, file_source, source_sheet, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_company = """
            INSERT INTO inspection_company (base_id, sampled_company, manufacturer)
            VALUES (%s, %s, %s)
        """
        insert_qualified = """
            INSERT INTO inspection_qualified (base_id, result_label, food_name, category)
            VALUES (%s, '合格', %s, %s)
        """
        insert_unqualified = """
            INSERT INTO inspection_unqualified
              (base_id, result_label, food_name, category, unqualified_item, test_result, standard_value)
            VALUES (%s, '不合格', %s, %s, %s, %s, %s)
        """
        insert_address = """
            INSERT INTO inspection_address (base_id, address, region)
            VALUES (%s, %s, %s)
        """

        while True:
            cur.execute(
                f"SELECT * FROM `{source_table}` WHERE id > %s ORDER BY id LIMIT %s",
                (last_id, batch_size),
            )
            rows = cur.fetchall()
            if not rows:
                break

            base_batch: list[tuple] = []
            company_batch: list[tuple] = []
            qualified_batch: list[tuple] = []
            unqualified_batch: list[tuple] = []
            address_batch: list[tuple] = []

            for row in rows:
                row_id = int(row["id"])
                last_id = row_id
                province, city, year, county = _normalize_location(row)
                status_cn = "合格" if row.get("status") == "qualified" else "不合格"
                batch_serial = (row.get("serial_number") or "").strip()
                file_source = (row.get("file_source") or "").strip()
                source_sheet = (row.get("source_sheet") or "").strip()
                created_at = row.get("created_at")

                base_batch.append(
                    (row_id, province, city, year, status_cn, batch_serial, file_source, source_sheet, created_at)
                )

                sampled = (row.get("sampled_company_name") or "").strip()
                manufacturer = (row.get("manufacturer_name") or "").strip()
                if manufacturer == "/":
                    manufacturer = ""
                company_batch.append((row_id, sampled, manufacturer))

                food_name = (row.get("food_name") or "").strip()
                category = (row.get("category") or "").strip()
                address = (row.get("sampled_company_address") or row.get("manufacturer_address") or "").strip()
                region = _build_region(province, city, county)
                address_batch.append((row_id, address, region))

                if status_cn == "合格":
                    qualified_batch.append((row_id, food_name, category))
                    qualified_n += 1
                else:
                    item, measured, standard = _extract_test_standard(row)
                    unqualified_batch.append((row_id, food_name, category, item, measured, standard))
                    unqualified_n += 1

                migrated += 1

            cur.executemany(insert_base, base_batch)
            cur.executemany(insert_company, company_batch)
            cur.executemany(insert_address, address_batch)
            if qualified_batch:
                cur.executemany(insert_qualified, qualified_batch)
            if unqualified_batch:
                cur.executemany(insert_unqualified, unqualified_batch)

            print(f"已迁移 {migrated}/{total}（合格 {qualified_n}，不合格 {unqualified_n}）…", flush=True)

        cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
        next_id = int(cur.fetchone()["n"])
        cur.execute(f"ALTER TABLE inspection_base AUTO_INCREMENT = {next_id}")

        print(f"删除旧表 {_LEGACY_TABLE}…")
        cur.execute(f"DROP TABLE IF EXISTS `{_LEGACY_TABLE}`")

        print("创建兼容视图 food_inspection_records …")
        _create_compat_view(cur)

    print(f"完成：共 {migrated} 行，合格 {qualified_n}，不合格 {unqualified_n}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移到五表结构")
    parser.add_argument("--batch-size", type=int, default=3000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return migrate(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
