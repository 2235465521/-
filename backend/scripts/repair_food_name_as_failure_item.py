"""全库扫描：修复 food_name 误填为不合格项目/片段的记录。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT  # noqa: E402
from food_inspection.db import connection  # noqa: E402
from food_inspection.parser import parse_file  # noqa: E402
from food_inspection.parser.fields import (  # noqa: E402
    looks_like_inspection_item_not_product,
    sanitize_product_name,
)
from food_inspection.parser.text import normalize_product_name  # noqa: E402


def _resolve_disk_path(file_source: str) -> str:
    rel = (file_source or "").strip().replace("\\", "/")
    if not rel:
        return ""
    if rel.startswith("/") and os.path.isfile(rel):
        return rel
    joined = os.path.join(DATA_ROOT, rel)
    return joined if os.path.isfile(joined) else ""


def _match_from_reparse(file_source: str, company: str, item: str) -> str:
    path = _resolve_disk_path(file_source)
    if not path:
        return ""
    try:
        records = parse_file(path)
    except Exception:
        return ""
    company = (company or "").strip()
    item = (item or "").strip()
    for record in records:
        rec_company = (record.company or record.sampled_unit or "").strip()
        rec_item = (record.unqualified_item or "").strip()
        rec_product = sanitize_product_name(record.product or "")
        if not rec_product:
            continue
        if company and company not in rec_company and rec_company not in company:
            continue
        if item and rec_item and item not in rec_item and rec_item not in item:
            continue
        return rec_product
    return ""


def _target_name(raw: str, file_source: str, company: str, item: str) -> str:
    cleaned = sanitize_product_name(raw)
    if cleaned:
        return cleaned
    if looks_like_inspection_item_not_product(raw):
        reparsed = _match_from_reparse(file_source, company, item)
        if reparsed:
            return reparsed
        return ""
    normalized = normalize_product_name(raw)
    if normalized != raw:
        cleaned = sanitize_product_name(normalized)
        if cleaned:
            return cleaned
    return sanitize_product_name(raw)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    updated = cleared = unchanged = 0
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.id, b.file_source, c.sampled_company, c.manufacturer,
                   u.food_name, u.unqualified_item
            FROM inspection_base b
            JOIN inspection_unqualified u ON u.base_id = b.id
            LEFT JOIN inspection_company c ON c.base_id = b.id
            WHERE b.status = '不合格'
            """
        )
        rows = cur.fetchall()
        for row in rows:
            raw = (row["food_name"] or "").strip()
            if not raw:
                continue
            company = (row["sampled_company"] or row["manufacturer"] or "").strip()
            item = (row["unqualified_item"] or "").strip()
            new_name = _target_name(raw, row["file_source"] or "", company, item)
            if new_name == raw:
                unchanged += 1
                continue
            cur.execute(
                "UPDATE inspection_unqualified SET food_name = %s WHERE base_id = %s",
                (new_name, row["id"]),
            )
            if new_name:
                updated += 1
            else:
                cleared += 1
        conn.commit()
    print(f"全库扫描 {len(rows)} 条不合格记录")
    print(f"已修复产品名: {updated} 条，已清空无效产品名: {cleared} 条，未变: {unchanged} 条")


if __name__ == "__main__":
    main()
