"""同品名分类回填：表内已有分类的样品名，补全同批空分类行。"""

from __future__ import annotations

import re
from collections import Counter

from food_inspection.category_junk import is_junk_category
from food_inspection.parser.text import _clean, normalize_product_name, strip_product_enumeration_suffix

_CATEGORY_EMPTY = frozenset(
    {"", "/", "-", "—", "无", "暂无", "不详", "未知", "nan", "none", "null", "未分类"}
)

# 品名括号内常见分类提示
_PAREN_CATEGORY_HINTS = (
    "调味品",
    "非即食类调味料",
    "方便食品",
    "食用农产品",
    "餐饮食品",
    "糕点",
    "饮料",
    "酒类",
    "速冻食品",
)


def _valid_category(category: str) -> str:
    cat = _clean(category)
    if cat in _CATEGORY_EMPTY:
        return ""
    if is_junk_category(cat):
        return ""
    return cat


def product_match_key(name: str) -> str:
    """白芷 / 白芷（调味品）/ 白芷1 → 白芷"""
    text = strip_product_enumeration_suffix(normalize_product_name(name))
    compact = re.sub(r"\s+", "", text)
    for hint in _PAREN_CATEGORY_HINTS:
        compact = re.sub(rf"[（(]{re.escape(hint)}[^）)]*[）)]$", "", compact)
        compact = re.sub(rf"[（(]{re.escape(hint)}[）)]$", "", compact)
    compact = re.sub(r"[（(][^）)]*[）)]$", "", compact)
    return compact.strip()


def _category_from_product_name(name: str) -> str:
    for hint in _PAREN_CATEGORY_HINTS:
        if re.search(rf"[（(]{re.escape(hint)}", name):
            return hint
    return ""


def build_category_map(records: list) -> dict[str, str]:
    """从一批记录中统计每个品名最常见的有效分类。"""
    votes: dict[str, Counter[str]] = {}
    for record in records:
        key = product_match_key(record.product)
        if not key:
            continue
        cat = _valid_category(record.category)
        if not cat:
            cat = _category_from_product_name(record.product)
        if not cat:
            continue
        votes.setdefault(key, Counter())[cat] += 1

    result: dict[str, str] = {}
    for key, counter in votes.items():
        result[key] = counter.most_common(1)[0][0]
    return result


def merge_category_maps(*maps: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for mapping in maps:
        merged.update(mapping)
    return merged


def backfill_record_category(record, category_map: dict[str, str]) -> None:
    if _valid_category(record.category):
        return
    key = product_match_key(record.product)
    if key and key in category_map:
        record.category = category_map[key]
        return
    hint = _category_from_product_name(record.product)
    if hint:
        record.category = hint


def backfill_categories_in_batch(records: list) -> list:
    """单文件/单批记录内按品名回填分类。"""
    mapping = build_category_map(records)
    for record in records:
        backfill_record_category(record, mapping)
    return records
