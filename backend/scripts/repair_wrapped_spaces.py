#!/usr/bin/env python3
"""修复 PDF/Excel 换行写入库的多余空格（单位名、产品名、地址等）。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.db import connection  # noqa: E402
from food_inspection.parser.text import (  # noqa: E402
    collapse_wrapped_chinese_text,
    normalize_company_name,
    normalize_product_name,
)

_BATCH = 2000


def _fix_text(value: str | None, *, company: bool = False, product: bool = False) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if company:
        return normalize_company_name(text)
    if product:
        return normalize_product_name(text)
    return collapse_wrapped_chinese_text(text)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    updated = {"company": 0, "address": 0, "qualified": 0, "unqualified": 0}

    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT base_id, sampled_company, manufacturer FROM inspection_company")
        rows = cur.fetchall()
        company_updates: list[tuple[str, str, int]] = []
        for row in rows:
            sampled = _fix_text(row["sampled_company"], company=True)
            manufacturer = _fix_text(row["manufacturer"], company=True)
            if sampled != (row["sampled_company"] or "") or manufacturer != (
                row["manufacturer"] or ""
            ):
                company_updates.append((sampled, manufacturer, row["base_id"]))
        for i in range(0, len(company_updates), _BATCH):
            batch = company_updates[i : i + _BATCH]
            cur.executemany(
                "UPDATE inspection_company SET sampled_company=%s, manufacturer=%s WHERE base_id=%s",
                batch,
            )
            updated["company"] += cur.rowcount

        cur.execute(
            "SELECT base_id, address, manufacturer_address, region FROM inspection_address"
        )
        addr_updates: list[tuple[str, str, str, int]] = []
        for row in cur.fetchall():
            address = _fix_text(row["address"])
            manufacturer_address = _fix_text(row["manufacturer_address"])
            region = _fix_text(row["region"])
            if (
                address != (row["address"] or "")
                or manufacturer_address != (row["manufacturer_address"] or "")
                or region != (row["region"] or "")
            ):
                addr_updates.append(
                    (address, manufacturer_address, region, row["base_id"])
                )
        for i in range(0, len(addr_updates), _BATCH):
            batch = addr_updates[i : i + _BATCH]
            cur.executemany(
                """
                UPDATE inspection_address
                SET address=%s, manufacturer_address=%s, region=%s
                WHERE base_id=%s
                """,
                batch,
            )
            updated["address"] += cur.rowcount

        cur.execute("SELECT base_id, food_name, category FROM inspection_qualified")
        q_updates: list[tuple[str, str, int]] = []
        for row in cur.fetchall():
            food = _fix_text(row["food_name"], product=True)
            category = _fix_text(row["category"])
            if food != (row["food_name"] or "") or category != (row["category"] or ""):
                q_updates.append((food, category, row["base_id"]))
        for i in range(0, len(q_updates), _BATCH):
            batch = q_updates[i : i + _BATCH]
            cur.executemany(
                "UPDATE inspection_qualified SET food_name=%s, category=%s WHERE base_id=%s",
                batch,
            )
            updated["qualified"] += cur.rowcount

        cur.execute(
            """
            SELECT base_id, food_name, category, unqualified_item, test_result, standard_value
            FROM inspection_unqualified
            """
        )
        u_updates: list[tuple[str, str, str, str, str, int]] = []
        for row in cur.fetchall():
            food = _fix_text(row["food_name"], product=True)
            category = _fix_text(row["category"])
            item = _fix_text(row["unqualified_item"])
            test_result = _fix_text(row["test_result"])
            standard = _fix_text(row["standard_value"])
            if (
                food != (row["food_name"] or "")
                or category != (row["category"] or "")
                or item != (row["unqualified_item"] or "")
                or test_result != (row["test_result"] or "")
                or standard != (row["standard_value"] or "")
            ):
                u_updates.append(
                    (food, category, item, test_result, standard, row["base_id"])
                )
        for i in range(0, len(u_updates), _BATCH):
            batch = u_updates[i : i + _BATCH]
            cur.executemany(
                """
                UPDATE inspection_unqualified
                SET food_name=%s, category=%s, unqualified_item=%s,
                    test_result=%s, standard_value=%s
                WHERE base_id=%s
                """,
                batch,
            )
            updated["unqualified"] += cur.rowcount

        conn.commit()

    print(
        "修复完成："
        f"单位 {updated['company']}，地址 {updated['address']}，"
        f"合格 {updated['qualified']}，不合格 {updated['unqualified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
