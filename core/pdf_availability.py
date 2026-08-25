"""检索列表 has_pdf：库记录 + 文件名含标准号；可选磁盘轻量校验。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.std_normalize import filename_contains_std_id


def _compact_sql_expr(column: str) -> str:
    """SQL 侧紧凑化（去常见分隔符），用于 pdf_only 过滤近似匹配。"""
    expr = column
    for ch in ("/", " ", "-", "_", ".", "／", "—", "－"):
        escaped = ch.replace("'", "''").replace("\\", "\\\\")
        expr = f"REPLACE({expr}, '{escaped}', '')"
    return f"UPPER({expr})"


def pdf_only_exists_sql(mysql: bool = False) -> str:
    """EXISTS 子句：filepath 存在且 file_name 紧凑串包含 std_id 紧凑串。"""
    fn = _compact_sql_expr("f.file_name")
    sid = _compact_sql_expr("b.std_id")
    if mysql:
        like_expr = f"CONCAT('%', {sid}, '%')"
    else:
        like_expr = f"'%' || {sid} || '%'"
    return (
        f"EXISTS (SELECT 1 FROM std_filepath f "
        f"WHERE f.base_id = b.id "
        f"AND f.file_name IS NOT NULL AND TRIM(f.file_name) <> '' "
        f"AND {fn} LIKE {like_expr})"
    )


def record_matches_std(std_id: str, file_name: str) -> bool:
    name = (file_name or "").strip()
    if not name or not (std_id or "").strip():
        return False
    return filename_contains_std_id(name, std_id)


def batch_has_pdf_map(
    file_rows: list[dict],
    std_by_id: dict[int, str],
    *,
    verify_disk: bool = False,
) -> dict[int, bool]:
    """按 base_id 批量计算 has_pdf。"""
    by_base: dict[int, list[dict]] = defaultdict(list)
    for fr in file_rows:
        bid = fr.get("base_id")
        if bid is None:
            continue
        by_base[int(bid)].append(fr)

    out: dict[int, bool] = {}
    for bid, std_id in std_by_id.items():
        out[bid] = _has_pdf_from_records(
            std_id, by_base.get(bid, []), verify_disk=verify_disk
        )
    return out


def _has_pdf_from_records(
    std_id: str,
    records: list[dict],
    *,
    verify_disk: bool,
) -> bool:
    if not (std_id or "").strip():
        return False

    for rec in records:
        name = (rec.get("file_name") or "").strip()
        if not record_matches_std(std_id, name):
            continue
        if not verify_disk:
            return True
        from core.pdf_service import find_pdf_on_disk

        found = find_pdf_on_disk(
            rec.get("file_path") or "",
            name,
            std_id=std_id,
            scan_disk=False,
        )
        if found:
            return True

    if verify_disk:
        from core.pdf_discovery import check_file_exists_in_cache, discover_pdfs_on_disk

        for hit in discover_pdfs_on_disk(std_id, limit=3):
            if filename_contains_std_id(hit.name, std_id) and check_file_exists_in_cache(hit):
                return True
    return False
