"""五表读写：按 file_source 加载、删除、批量写入。"""

from __future__ import annotations

from collections import defaultdict

from food_inspection.db import connection
from food_inspection.parser.models import Record


def load_records_by_file_source() -> dict[str, list[Record]]:
    """一次性加载全部已入库记录，按 file_source 分组。"""
    sql = """
        SELECT
          b.id,
          CASE b.status WHEN '合格' THEN 'qualified' WHEN '不合格' THEN 'unqualified' ELSE b.status END AS status,
          b.province,
          b.city,
          b.year,
          b.file_source,
          b.source_sheet,
          b.batch_serial,
          c.sampled_company,
          c.manufacturer,
          a.address,
          a.manufacturer_address,
          a.region,
          COALESCE(q.food_name, u.food_name) AS food_name,
          COALESCE(q.category, u.category) AS category,
          COALESCE(u.unqualified_item, '') AS unqualified_item,
          COALESCE(u.test_result, '') AS test_result,
          COALESCE(u.standard_value, '') AS standard_value
        FROM inspection_base b
        LEFT JOIN inspection_company c ON c.base_id = b.id
        LEFT JOIN inspection_address a ON a.base_id = b.id
        LEFT JOIN inspection_qualified q ON q.base_id = b.id
        LEFT JOIN inspection_unqualified u ON u.base_id = b.id
        ORDER BY b.id
    """
    grouped: dict[str, list[Record]] = defaultdict(list)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            rel = (row["file_source"] or "").strip()
            if not rel:
                continue
            item = row["unqualified_item"] or ""
            test = row["test_result"] or ""
            standard = row["standard_value"] or ""
            reason = ""
            if standard or test:
                reason = f"标准: {standard}；实测: {test}"
            elif item:
                reason = f"不合格项目：{item}"

            grouped[rel].append(
                Record(
                    status=row["status"] or "qualified",
                    company=row["sampled_company"] or "",
                    product=row["food_name"] or "",
                    province=row["province"] or "",
                    city=row["city"] or "",
                    province_city=row["region"] or "",
                    unqualified_item=item,
                    reason=reason,
                    category=row["category"] or "",
                    source_file=rel,
                    source_file_name=rel.split("/")[-1],
                    source_sheet=row["source_sheet"] or "",
                    source_province=row["province"] or "",
                    source_city=row["city"] or "",
                    sampled_unit=row["sampled_company"] or "",
                    manufacturer=row["manufacturer"] or "",
                    address=row["address"] or "",
                    manufacturer_address=row["manufacturer_address"] or "",
                    serial_number=row["batch_serial"] or "",
                    year=row["year"] or "",
                )
            )
    return dict(grouped)


def load_imported_file_keys() -> set[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT file_source FROM inspection_base")
        return {(row["file_source"] or "").strip() for row in cur.fetchall() if row["file_source"]}


def delete_file_source(cur, rel_key: str) -> int:
    cur.execute("DELETE FROM inspection_base WHERE file_source = %s", (rel_key,))
    return int(cur.rowcount or 0)


def repair_row_in_db(cur, base_id: int, record: Record) -> None:
    """将 guard 后的记录写回单行（不重导整文件时用）。"""
    from food_inspection.mysql_v2 import record_to_rows

    rows = record_to_rows(record, base_id)
    base = rows["base"]
    company = rows["company"]
    address = rows["address"]

    cur.execute(
        """
        UPDATE inspection_base
        SET status = %s, batch_serial = %s, source_sheet = %s
        WHERE id = %s
        """,
        (base[4], base[5], base[7], base_id),
    )
    cur.execute(
        """
        UPDATE inspection_company
        SET sampled_company = %s, manufacturer = %s
        WHERE base_id = %s
        """,
        (company[1], company[2], base_id),
    )
    cur.execute(
        """
        UPDATE inspection_address
        SET address = %s, manufacturer_address = %s, region = %s
        WHERE base_id = %s
        """,
        (address[1], address[2], address[3], base_id),
    )

    if record.status == "qualified":
        cur.execute("DELETE FROM inspection_unqualified WHERE base_id = %s", (base_id,))
        if "qualified" in rows:
            q = rows["qualified"]
            cur.execute(
                """
                INSERT INTO inspection_qualified (base_id, result_label, food_name, category)
                VALUES (%s, '合格', %s, %s)
                ON DUPLICATE KEY UPDATE food_name = VALUES(food_name), category = VALUES(category)
                """,
                (base_id, q[1], q[2]),
            )
    else:
        cur.execute("DELETE FROM inspection_qualified WHERE base_id = %s", (base_id,))
        if "unqualified" in rows:
            u = rows["unqualified"]
            cur.execute(
                """
                INSERT INTO inspection_unqualified
                  (base_id, result_label, food_name, category, unqualified_item, test_result, standard_value)
                VALUES (%s, '不合格', %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  food_name = VALUES(food_name),
                  category = VALUES(category),
                  unqualified_item = VALUES(unqualified_item),
                  test_result = VALUES(test_result),
                  standard_value = VALUES(standard_value)
                """,
                (base_id, u[1], u[2], u[3], u[4], u[5]),
            )
