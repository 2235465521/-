"""记录指纹：用于比对「库内数据」与「重新解析」是否一致。"""

from __future__ import annotations

import re
from collections import Counter

from food_inspection.parser.fields import sanitize_product_name
from food_inspection.parser.layout import normalize_company_name
from food_inspection.parser.models import Record
from food_inspection.parser.text import _clean


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", _clean(text))


def record_fingerprint(record: Record) -> tuple:
    status = "unqualified" if record.status == "unqualified" else "qualified"
    return (
        status,
        _norm_text(sanitize_product_name(record.product or "")),
        _norm_text(normalize_company_name(record.sampled_unit or record.company or "")),
        _norm_text(normalize_company_name(record.manufacturer or "")),
        _norm_text(record.category or ""),
        _norm_text(record.unqualified_item or "")[:120],
        _norm_text(record.source_sheet or ""),
    )


def records_fingerprint(records: list[Record]) -> Counter:
    return Counter(record_fingerprint(r) for r in records)


def fingerprints_match(left: list[Record], right: list[Record]) -> bool:
    return records_fingerprint(left) == records_fingerprint(right)
