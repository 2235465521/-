"""商品名称标准化：分类前剥离品牌、口味、形态等干扰属性。"""

from __future__ import annotations

import re

from food_inspection.parser.fields import PROVINCE_NAMES
from food_inspection.parser.text import (
    collapse_wrapped_chinese_text,
    strip_product_enumeration_suffix,
)

_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_WEIGHT_SPEC_RE = re.compile(
    r"(?:\d+(?:\.\d+)?(?:g|kg|ml|l|升|克|千克|毫升|斤)|"
    r"[一二三四五六七八九十百千两半]+(?:斤|克|千克|毫升|升))"
)
_TRAILING_SPEC_RE = re.compile(r"[\dA-Za-z号级型款装盒袋瓶包罐条只个片枚支根把束斤克千克毫升升L]+$")

_ORIGIN_PREFIXES: tuple[str, ...] = tuple(
    sorted(
        {
            *PROVINCE_NAMES,
            "内蒙古",
            "黑龙江",
            "广西壮族",
            "西藏",
            "宁夏",
            "新疆",
            "泰国",
            "越南",
            "进口",
            "国产",
            "本地",
            "当地",
        },
        key=len,
        reverse=True,
    )
)
_ORIGIN_PREFIX_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in _ORIGIN_PREFIXES) + r")"
)

_FORM_PREFIXES: tuple[str, ...] = (
    "纯切",
    "夹心",
    "散装",
    "散称",
    "自制",
    "切片",
    "精品",
    "特级",
    "一级",
    "优选",
    "优质",
    "有机",
    "绿色",
    "无公害",
    "包装",
    "称重",
    "精选",
    "特选",
    "普通",
    "常规",
    "大",
    "小",
    "圆",
    "鲜",
    "干",
)

_QUALITY_PREFIXES: tuple[str, ...] = (
    "新鲜",
    "当季",
    "时令",
)

_EXTRA_STRIP_SUFFIXES: tuple[str, ...] = (
    "散装称重",
    "散称称重",
    "计量称重",
    "散装",
    "散称",
    "称重",
    "（散装）",
    "(散装)",
)

# 整词保护：剥离口味时不得破坏
_FLAVOR_PROTECTED: frozenset[str] = frozenset(
    {"调味品", "味精", "鸡精", "五香粉", "十三香", "火锅底料"}
)

_INSTITUTION_MARKERS: tuple[str, ...] = (
    "餐饮服务有限公司",
    "食品有限公司",
    "有限公司",
    "有限责任公司",
    "餐饮店",
    "餐饮店（",
    "食堂",
    "餐厅",
    "饭店",
    "酒店",
    "药店",
    "药房",
    "幼儿园",
    "小学",
    "中学",
    "大学",
    "养老院",
    "福利院",
    "分店",
    "经营部",
    "商行",
    "专卖店",
    "研究所",
    "卫生院",
    "服务中心",
)

_BRAND_PREFIX_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fa5]{1,8}(?=[\u4e00-\u9fa5]{2,})")


def compact_product_name(name: str) -> str:
    text = collapse_wrapped_chinese_text(name)
    text = strip_product_enumeration_suffix(text) or text
    return re.sub(r"\s+", "", text)


def is_institution_name(name: str) -> bool:
    compact = compact_product_name(name)
    if not compact:
        return False
    if any(marker in compact for marker in _INSTITUTION_MARKERS):
        if not _looks_like_food_product(compact):
            return True
    if compact.endswith(("公司", "食堂", "药店", "药房", "幼儿园", "小学", "中学")):
        if not _looks_like_food_product(compact):
            return True
    return False


def _looks_like_food_product(name: str) -> bool:
    food_hints = (
        "蛋糕",
        "面包",
        "饼干",
        "薯片",
        "糖果",
        "牛奶",
        "酸奶",
        "饮料",
        "啤酒",
        "白酒",
        "火腿",
        "香肠",
        "火锅底料",
        "酱油",
        "食醋",
        "大米",
        "面条",
        "馒头",
        "包子",
        "粽子",
        "月饼",
    )
    return any(hint in name for hint in food_hints)


def strip_for_classification(name: str) -> tuple[str, list[str]]:
    """按分类规范剥离干扰属性，返回 (核心文本, 步骤说明)。"""
    raw = compact_product_name(name)
    if not raw:
        return "", ["空名称"]

    steps: list[str] = []
    current = raw

    no_paren = _PAREN_RE.sub("", current).strip()
    if no_paren and no_paren != current:
        current = no_paren
        steps.append("去括号说明")

    stripped, weight_steps = _strip_weight_specs(current)
    if stripped != current:
        current = stripped
        steps.extend(weight_steps)

    stripped, flavor_steps = _strip_flavor_phrases(current)
    if stripped != current:
        current = stripped
        steps.extend(flavor_steps)

    stripped, origin_steps = _strip_origin(current)
    if stripped != current:
        current = stripped
        steps.extend(origin_steps)

    for prefix_group in (_FORM_PREFIXES, _QUALITY_PREFIXES):
        stripped, prefix_steps = _strip_prefixes(current, prefix_group)
        if stripped != current:
            current = stripped
            steps.extend(prefix_steps)

    for suffix in _EXTRA_STRIP_SUFFIXES:
        if current.endswith(suffix) and len(current) > len(suffix) + 1:
            current = current[: -len(suffix)]
            steps.append(f"去后缀「{suffix}」")

    current = _TRAILING_SPEC_RE.sub("", current).strip()

    stripped, brand_steps = _strip_brand_prefix(current)
    if stripped != current:
        current = stripped
        steps.extend(brand_steps)

    # 再次剥离形态前缀（品牌去除后可能露出）
    for prefix_group in (_FORM_PREFIXES, _QUALITY_PREFIXES):
        stripped, prefix_steps = _strip_prefixes(current, prefix_group)
        if stripped != current:
            current = stripped
            steps.extend(prefix_steps)

    return current or raw, steps


def _strip_prefixes(name: str, prefixes: tuple[str, ...]) -> tuple[str, list[str]]:
    steps: list[str] = []
    current = name
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if current.startswith(prefix) and len(current) > len(prefix) + 1:
                current = current[len(prefix) :]
                steps.append(f"去形态/修饰「{prefix}」")
                changed = True
                break
    return current, steps


def _strip_origin(name: str) -> tuple[str, list[str]]:
    steps: list[str] = []
    current = name
    while True:
        match = _ORIGIN_PREFIX_RE.match(current)
        if not match:
            break
        token = match.group(1)
        rest = current[len(token) :]
        if len(rest) < 2:
            break
        current = rest
        steps.append(f"去产地「{token}」")
    return current, steps


def _strip_weight_specs(name: str) -> tuple[str, list[str]]:
    steps: list[str] = []
    current = _WEIGHT_SPEC_RE.sub("", name).strip()
    if current != name:
        steps.append("去规格重量")
    return current or name, steps


def _strip_flavor_phrases(name: str) -> tuple[str, list[str]]:
    if name in _FLAVOR_PROTECTED:
        return name, []

    steps: list[str] = []
    current = name
    changed = True
    while changed and current not in _FLAVOR_PROTECTED:
        changed = False
        match = re.search(
            r"^(.{0,12}?)([\u4e00-\u9fa5]{2,15}(?:口味|风味|口感|味))(.{2,})$",
            current,
        )
        if match:
            current = (match.group(1) + match.group(3)).strip()
            steps.append(f"去口味「{match.group(2)}」")
            changed = True
            continue
        prefix = re.match(r"^[\u4e00-\u9fa5]{2,15}(?:口味|风味|口感|味)(.+)$", current)
        if prefix and len(prefix.group(1)) >= 2:
            current = prefix.group(1)
            steps.append("去口味前缀")
            changed = True
    return current, steps


def _strip_brand_prefix(name: str) -> tuple[str, list[str]]:
    match = _BRAND_PREFIX_RE.match(name)
    if not match:
        return name, []
    rest = name[match.end() :]
    if len(rest) >= 2:
        return rest, ["去品牌前缀"]
    return name, []
