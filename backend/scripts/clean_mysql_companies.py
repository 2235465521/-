#!/usr/bin/env python3
"""清洗 MySQL 单位名与不合格项目：无效名、检验机构、生产单位与被抽检单位重复等。"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.parser.fields import normalize_failure_item_name  # noqa: E402
from food_inspection.parser.text import (  # noqa: E402
    is_inspection_agency,
    is_invalid_company,
    normalize_company_name,
)


def clean_company_fields(sampled: str, manufacturer: str) -> tuple[str, str]:
    sampled = normalize_company_name(sampled)
    manufacturer = normalize_company_name(manufacturer)
    if manufacturer in ("/", "—", "-", "--", "\\"):
        manufacturer = ""

    if sampled and (is_invalid_company(sampled) or is_inspection_agency(sampled)):
        sampled = ""
    if manufacturer and (is_invalid_company(manufacturer) or is_inspection_agency(manufacturer)):
        manufacturer = ""
    if sampled and manufacturer and sampled == manufacturer:
        manufacturer = ""
    return sampled[:255], manufacturer[:255]


def clean_companies(*, batch_size: int, dry_run: bool) -> dict[str, int]:
    from food_inspection.db import connection

    stats = Counter()
    last_id = 0

    select_sql = """
        SELECT base_id, sampled_company, manufacturer
        FROM inspection_company
        WHERE base_id > %s
        ORDER BY base_id
        LIMIT %s
    """
    update_sql = """
        UPDATE inspection_company
        SET sampled_company = %s, manufacturer = %s
        WHERE base_id = %s
    """

    with connection() as conn, conn.cursor() as cur:
        while True:
            cur.execute(select_sql, (last_id, batch_size))
            rows = cur.fetchall()
            if not rows:
                break

            batch: list[tuple[str, str, int]] = []
            for row in rows:
                stats["scanned"] += 1
                last_id = int(row["base_id"])
                old_s = (row["sampled_company"] or "").strip()
                old_m = (row["manufacturer"] or "").strip()
                new_s, new_m = clean_company_fields(old_s, old_m)
                if new_s == old_s and new_m == old_m:
                    continue
                stats["updated"] += 1
                if old_s and not new_s:
                    stats["cleared_sampled"] += 1
                if old_m and not new_m:
                    stats["cleared_manufacturer"] += 1
                if old_s != new_s and new_s:
                    stats["normalized_sampled"] += 1
                if old_m != new_m and new_m:
                    stats["normalized_manufacturer"] += 1
                batch.append((new_s, new_m, last_id))

            if batch and not dry_run:
                cur.executemany(update_sql, batch)

            if stats["scanned"] % 50000 < batch_size:
                print(
                    f"单位表：已扫描 {stats['scanned']}，待更新 {stats['updated']}…",
                    flush=True,
                )

    return dict(stats)


def clean_failure_items(*, batch_size: int, dry_run: bool) -> dict[str, int]:
    from food_inspection.db import connection

    stats = Counter()
    last_id = 0

    select_sql = """
        SELECT base_id, unqualified_item
        FROM inspection_unqualified
        WHERE base_id > %s
        ORDER BY base_id
        LIMIT %s
    """
    update_sql = """
        UPDATE inspection_unqualified
        SET unqualified_item = %s
        WHERE base_id = %s
    """

    with connection() as conn, conn.cursor() as cur:
        while True:
            cur.execute(select_sql, (last_id, batch_size))
            rows = cur.fetchall()
            if not rows:
                break

            batch: list[tuple[str, int]] = []
            for row in rows:
                stats["scanned"] += 1
                last_id = int(row["base_id"])
                raw = (row["unqualified_item"] or "").strip()
                if not raw:
                    continue
                norm = normalize_failure_item_name(raw)
                if not norm or norm == raw:
                    continue
                stats["updated"] += 1
                batch.append((norm[:255], last_id))

            if batch and not dry_run:
                cur.executemany(update_sql, batch)

    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗 inspection_company 与不合格项目")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    parser.add_argument("--companies-only", action="store_true")
    parser.add_argument("--items-only", action="store_true")
    args = parser.parse_args()

    mode = "（预览，未写库）" if args.dry_run else ""

    if not args.items_only:
        company_stats = clean_companies(batch_size=args.batch_size, dry_run=args.dry_run)
        print(
            f"单位表{mode}：扫描 {company_stats.get('scanned', 0)} 行，"
            f"更新 {company_stats.get('updated', 0)} 行 "
            f"（清空被抽检 {company_stats.get('cleared_sampled', 0)}，"
            f"清空生产 {company_stats.get('cleared_manufacturer', 0)}，"
            f"归一化被抽检 {company_stats.get('normalized_sampled', 0)}，"
            f"归一化生产 {company_stats.get('normalized_manufacturer', 0)}）"
        )

    if not args.companies_only:
        item_stats = clean_failure_items(batch_size=args.batch_size, dry_run=args.dry_run)
        print(
            f"不合格项目{mode}：扫描 {item_stats.get('scanned', 0)} 行，"
            f"归一化更新 {item_stats.get('updated', 0)} 行"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
