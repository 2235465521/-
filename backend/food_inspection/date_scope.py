"""按源文件路径中的公告年份筛选记录。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_YEAR_SEGMENT = re.compile(r"^20\d{2}$")


def resolve_record_year(record: dict[str, Any]) -> int | None:
    """从 source_file 路径中提取数据年份（如 ...\\呼和浩特市\\2024\\公告...）。"""
    path = (record.get("source_file") or "").replace("/", "\\")
    for part in path.split("\\"):
        if _YEAR_SEGMENT.fullmatch(part):
            return int(part)
    return None


def _parse_iso_date(val: str | None, default: date) -> date:
    if not val:
        return default
    try:
        return date.fromisoformat(val.strip())
    except (ValueError, TypeError):
        match = re.search(r"20\d{2}", str(val))
        if match:
            return date(int(match.group()), 1, 1)
        return default


def record_in_date_range(
    record: dict[str, Any],
    date_from: str | None,
    date_to: str | None,
) -> bool:
    if not date_from and not date_to:
        return True

    year = resolve_record_year(record)
    if year is None:
        return False

    start = _parse_iso_date(date_from, date(2000, 1, 1))
    end = _parse_iso_date(date_to, date(2099, 12, 31))
    rec_start = date(year, 1, 1)
    rec_end = date(year, 12, 31)
    return rec_start <= end and rec_end >= start


def filter_records_by_date_range(
    records: list[dict[str, Any]],
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    if not date_from and not date_to:
        return records
    return [r for r in records if record_in_date_range(r, date_from, date_to)]
