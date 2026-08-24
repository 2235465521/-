"""解析后记录校验与纠错（汇总历史修复经验）。"""

from __future__ import annotations

import os
import re

from food_inspection.analytics import resolve_category_from_mysql_row
from food_inspection.category_junk import is_junk_category
from food_inspection.parser import parse_file
from food_inspection.parser.classification import _detect_file_mode
from food_inspection.parser.category_fill import backfill_categories_in_batch
from food_inspection.parser.fields import (
    looks_like_inspection_item_not_product,
    sanitize_product_name,
    source_relative_key,
)
from food_inspection.parser.layout import normalize_company_name
from food_inspection.parser.models import Record
from food_inspection.parser.text import (
    _clean,
    collapse_wrapped_chinese_text,
    is_inspection_agency,
    is_invalid_company,
    normalize_product_name,
)

_FAILURE_MARKERS = ("mg/kg", "mg/L", "不得检出", "║", "||", "实测", "标准")


def _is_disposal_qualified_noise(record: Record, filepath: str) -> bool:
    """核查处置/风险控制正文误标合格。"""
    if record.status != "qualified":
        return False
    rel = source_relative_key(filepath) or filepath.replace("\\", "/")
    if "_正文" not in rel:
        return False
    return "核查处置" in rel or "风险控制" in rel


def _looks_like_test_items_list(item: str) -> bool:
    """逗号分隔的多项检测清单（非单项不合格结论）。"""
    text = _clean(item)
    if not text:
        return False
    if text.count(",") + text.count("，") < 2:
        return False
    if any(marker in text for marker in _FAILURE_MARKERS):
        return False
    if text.startswith("不合格") or "超标" in text or "不得检出" in text:
        return False
    return True


def _has_failure_evidence(record: Record) -> bool:
    item = _clean(record.unqualified_item)
    reason = _clean(record.reason)
    if item and not _looks_like_test_items_list(item):
        return True
    if reason and any(marker in reason for marker in _FAILURE_MARKERS):
        return True
    if reason and any(k in reason for k in ("不合格", "超标", "检出", "不得")):
        return True
    return False


def _normalize_category(record: Record, filepath: str) -> str:
    rel = source_relative_key(filepath) or (record.source_file or "")
    return resolve_category_from_mysql_row(
        category=(record.category or "").strip(),
        food_name=(record.product or "").strip(),
        unqualified_item=(record.unqualified_item or "").strip(),
        unqualified_reason=(record.reason or "").strip(),
        file_source=rel,
    )


def guard_record(record: Record, filepath: str) -> tuple[Record, list[str]]:
    """单条记录纠错，返回 (记录, 问题码列表)。"""
    issues: list[str] = []

    record.company = collapse_wrapped_chinese_text(record.company or "")
    record.sampled_unit = collapse_wrapped_chinese_text(record.sampled_unit or "")
    record.manufacturer = collapse_wrapped_chinese_text(record.manufacturer or "")
    record.address = collapse_wrapped_chinese_text(record.address or "")
    record.manufacturer_address = collapse_wrapped_chinese_text(
        record.manufacturer_address or ""
    )
    record.province_city = collapse_wrapped_chinese_text(record.province_city or "")

    company = normalize_company_name(record.company or "")
    sampled = normalize_company_name(record.sampled_unit or company or "")
    manufacturer = normalize_company_name(record.manufacturer or "")
    if manufacturer in ("/", "—", "-", "无", "暂无", "不详"):
        manufacturer = ""
    if manufacturer and manufacturer == sampled:
        manufacturer = ""

    if is_invalid_company(sampled) or is_inspection_agency(sampled):
        if company and not is_invalid_company(company):
            sampled = normalize_company_name(company)
        else:
            issues.append("invalid_sampled_company")
    if manufacturer and (is_invalid_company(manufacturer) or is_inspection_agency(manufacturer)):
        manufacturer = ""
        issues.append("invalid_manufacturer")

    record.company = company
    record.sampled_unit = sampled
    record.manufacturer = manufacturer

    raw_product = record.product or ""
    product = sanitize_product_name(raw_product)
    if not product:
        product = sanitize_product_name(normalize_product_name(raw_product))
    if looks_like_inspection_item_not_product(product or raw_product):
        issues.append("product_looks_like_item")
        product = ""
    record.product = product

    raw_cat = (record.category or "").strip()
    if is_junk_category(raw_cat):
        issues.append("category_junk")
    new_cat = _normalize_category(record, filepath)
    if new_cat != raw_cat:
        issues.append("category_resolved")
    record.category = new_cat

    if record.status == "unqualified" and _detect_file_mode(os.path.basename(filepath)) == "qualified":
        record.status = "qualified"
        record.unqualified_item = ""
        record.reason = ""
        issues.append("qualified_file_row")
    elif record.status == "unqualified" and not _has_failure_evidence(record):
        record.status = "qualified"
        record.unqualified_item = ""
        record.reason = ""
        issues.append("false_unqualified")

    if _is_disposal_qualified_noise(record, filepath):
        issues.append("disposal_qualified_drop")
        return record, issues

    if not record.product and not sampled:
        issues.append("empty_product_and_company")

    return record, issues


def guard_file_records(
    records: list[Record],
    filepath: str,
) -> tuple[list[Record], dict[str, int]]:
    """批量纠错并过滤无效行。"""
    if not records:
        return [], {}

    backfill_categories_in_batch(records)
    kept: list[Record] = []
    issue_counts: dict[str, int] = {}

    for record in records:
        guarded, issues = guard_record(record, filepath)
        for code in issues:
            issue_counts[code] = issue_counts.get(code, 0) + 1
        if "disposal_qualified_drop" in issues:
            continue
        if "empty_product_and_company" in issues and not guarded.product:
            continue
        kept.append(guarded)

    return kept, issue_counts


def parse_file_guarded(filepath: str) -> tuple[list[Record], str | None, dict[str, int]]:
    """解析 + 统一纠错。"""
    try:
        raw = parse_file(filepath)
        guarded, issues = guard_file_records(raw, filepath)
        return guarded, None, issues
    except Exception as exc:
        return [], str(exc), {}
