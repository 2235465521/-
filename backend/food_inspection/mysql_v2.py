"""五表结构：建表、写入、兼容视图。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from food_inspection.db import connection
from food_inspection.food_category_map import lookup_categories
from food_inspection.parser.fields import (
    _split_combined_failure,
    normalize_failure_item_name,
    sanitize_product_name,
    source_relative_key,
)
from food_inspection.parser.text import normalize_company_name, normalize_product_name, collapse_wrapped_chinese_text
from food_inspection.parser.models import Record

_SCHEMA_FILE = Path(__file__).resolve().parents[1] / "sql" / "inspection_schema_v2.sql"
_YEAR_RE = re.compile(r"^20\d{2}$")


def init_schema(*, with_view: bool = False) -> None:
    sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    if not with_view:
        sql = sql.split("DROP VIEW IF EXISTS food_inspection_records", 1)[0]
    with connection() as conn, conn.cursor() as cur:
        for stmt in sql.split(";"):
            chunk = stmt.strip()
            if not chunk or chunk.startswith("--"):
                continue
            cur.execute(chunk)


def create_compat_view() -> None:
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
      a.manufacturer_address AS manufacturer_address,
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
      COALESCE(q.sub_category, u.sub_category) AS sub_category,
      '' AS remarks,
      b.created_at AS created_at
    FROM inspection_base b
    LEFT JOIN inspection_company c ON c.base_id = b.id
    LEFT JOIN inspection_address a ON a.base_id = b.id
    LEFT JOIN inspection_qualified q ON q.base_id = b.id
    LEFT JOIN inspection_unqualified u ON u.base_id = b.id
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute("DROP VIEW IF EXISTS food_inspection_records")
        cur.execute(view_sql)


def _normalize_city_year(province: str, city: str, year: str) -> tuple[str, str, str]:
    province = (province or "").strip()
    city = (city or "").strip()
    year = (year or "").strip()
    if _YEAR_RE.fullmatch(city):
        if not year:
            year = city
        city = ""
    return province, city, year


def _build_region(province: str, city: str, province_city: str) -> str:
    region = (province_city or "").strip()
    if region:
        return region.replace(" / ", "").replace("/", "").replace(" ", "")
    parts = [p for p in (province, city) if p and not _YEAR_RE.fullmatch(p)]
    return "".join(parts)


def extract_failure_values(item: str, reason: str) -> tuple[str, str, str]:
    item_name = normalize_failure_item_name(item)
    standard = ""
    measured = ""
    text = (reason or "").strip()

    std_match = re.search(r"标准[:：]\s*([^；;|║‖\n]+)", text)
    if std_match:
        standard = std_match.group(1).strip()

    meas_match = re.search(r"实测[:：]\s*([^（(\n；;]+)", text)
    if meas_match:
        segment = meas_match.group(1).strip()
        item_part, meas_part, std_part = _split_combined_failure(segment)
        if meas_part:
            measured = meas_part
        elif item_part and re.search(r"\d", item_part):
            measured = item_part
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
        _, meas2, std2 = _split_combined_failure(text)
        if meas2 and not measured:
            measured = meas2
        if std2 and not standard:
            standard = std2

    return item_name, measured[:255], standard[:255]


def record_to_rows(record: Record, base_id: int) -> dict[str, Any]:
    province, city, year = _normalize_city_year(
        record.source_province or record.province,
        record.source_city or record.city,
        record.year,
    )
    status_cn = "合格" if record.status == "qualified" else "不合格"
    file_source = source_relative_key(record.source_file)
    sampled = normalize_company_name(record.sampled_unit or record.company or "")[:255]
    manufacturer = normalize_company_name(record.manufacturer or "")[:255]
    if manufacturer in ("/", "—", "-"):
        manufacturer = ""
    if manufacturer and normalize_company_name(manufacturer) == normalize_company_name(sampled):
        manufacturer = ""
    address = collapse_wrapped_chinese_text(record.address or "")
    manufacturer_address = collapse_wrapped_chinese_text(record.manufacturer_address or "")
    region = _build_region(province, city, record.province_city)
    food_name = sanitize_product_name(record.product or "")[:255]
    mapped = lookup_categories(food_name)
    if mapped:
        category, sub_category = mapped[0][:100], mapped[1][:128]
    else:
        category, sub_category = "", ""
    serial = (record.serial_number or "").strip()

    rows: dict[str, Any] = {
        "base": (
            base_id,
            province,
            city,
            year,
            status_cn,
            serial,
            file_source,
            record.source_sheet or "",
        ),
        "company": (base_id, sampled, manufacturer),
        "address": (base_id, address, manufacturer_address, region),
    }
    if status_cn == "合格":
        rows["qualified"] = (base_id, food_name, category, sub_category)
    else:
        item, measured, standard = extract_failure_values(record.unqualified_item, record.reason)
        rows["unqualified"] = (
            base_id,
            food_name,
            category,
            sub_category,
            item[:255],
            measured[:255],
            standard[:255],
        )
    return rows


def insert_record(cur, record: Record, base_id: int) -> None:
    rows = record_to_rows(record, base_id)
    _insert_rows(cur, rows)


def _insert_rows(cur, rows: dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO inspection_base
          (id, province, city, year, status, batch_serial, file_source, source_sheet)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows["base"],
    )
    cur.execute(
        "INSERT INTO inspection_company (base_id, sampled_company, manufacturer) VALUES (%s, %s, %s)",
        rows["company"],
    )
    cur.execute(
        "INSERT INTO inspection_address (base_id, address, manufacturer_address, region) VALUES (%s, %s, %s, %s)",
        rows["address"],
    )
    if "qualified" in rows:
        cur.execute(
            """
            INSERT INTO inspection_qualified
              (base_id, result_label, food_name, category, sub_category)
            VALUES (%s, '合格', %s, %s, %s)
            """,
            rows["qualified"],
        )
    else:
        cur.execute(
            """
            INSERT INTO inspection_unqualified
              (base_id, result_label, food_name, category, sub_category,
               unqualified_item, test_result, standard_value)
            VALUES (%s, '不合格', %s, %s, %s, %s, %s, %s)
            """,
            rows["unqualified"],
        )


def insert_records_batch(cur, items: list[tuple[Record, int]]) -> None:
    if not items:
        return
    base_rows: list[tuple] = []
    company_rows: list[tuple] = []
    address_rows: list[tuple] = []
    qualified_rows: list[tuple] = []
    unqualified_rows: list[tuple] = []

    for record, base_id in items:
        rows = record_to_rows(record, base_id)
        base_rows.append(rows["base"])
        company_rows.append(rows["company"])
        address_rows.append(rows["address"])
        if "qualified" in rows:
            qualified_rows.append(rows["qualified"])
        else:
            unqualified_rows.append(rows["unqualified"])

    cur.executemany(
        """
        INSERT INTO inspection_base
          (id, province, city, year, status, batch_serial, file_source, source_sheet)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        base_rows,
    )
    cur.executemany(
        "INSERT INTO inspection_company (base_id, sampled_company, manufacturer) VALUES (%s, %s, %s)",
        company_rows,
    )
    cur.executemany(
        "INSERT INTO inspection_address (base_id, address, manufacturer_address, region) VALUES (%s, %s, %s, %s)",
        address_rows,
    )
    if qualified_rows:
        cur.executemany(
            """
            INSERT INTO inspection_qualified
              (base_id, result_label, food_name, category, sub_category)
            VALUES (%s, '合格', %s, %s, %s)
            """,
            qualified_rows,
        )
    if unqualified_rows:
        cur.executemany(
            """
            INSERT INTO inspection_unqualified
              (base_id, result_label, food_name, category, sub_category,
               unqualified_item, test_result, standard_value)
            VALUES (%s, '不合格', %s, %s, %s, %s, %s, %s)
            """,
            unqualified_rows,
        )
