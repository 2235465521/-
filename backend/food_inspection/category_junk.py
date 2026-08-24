"""非食品大类的 category 列脏值（日期、批号、规格等误写入分类列）。"""

from __future__ import annotations

import re

# 表头/说明字段误入 category 列
_CATEGORY_JUNK_MARKERS: tuple[str, ...] = (
    "购进日期",
    "购进时间",
    "生产日期",
    "加工日期",
    "保质期",
    "批号",
    "抽样单编号",
    "抽样编号",
    "检验依据",
    "备样数量",
    "样品数量",
    "规格型号",
    "净含量",
    "商标",
    "标称生产企业",
    "标称",
    "样品名称",
    "食品名称",
    "其他日期",
)

_CATEGORY_JUNK_RE = re.compile("|".join(re.escape(m) for m in _CATEGORY_JUNK_MARKERS))
_CATEGORY_DATE_IN_TEXT_RE = re.compile(r"20\d{2}[-/.年]\d{1,2}")
_CATEGORY_DATETIME_RE = re.compile(
    r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}:\d{2})?"
)
_CATEGORY_COMPACT_DATE_RE = re.compile(r"^20\d{2}\d{4}$")

# MySQL REGEXP（与 _CATEGORY_JUNK_MARKERS 同步）
MYSQL_CATEGORY_JUNK_REGEXP = (
    "购进日期|购进时间|生产日期|加工日期|保质期|批号|抽样单编号|抽样编号|检验依据|"
    "备样数量|样品数量|规格型号|净含量|商标|标称生产企业|标称|样品名称|食品名称|其他日期"
)


def is_junk_category(name: str | None) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    if _CATEGORY_JUNK_RE.search(text):
        return True
    if "日期" in text and re.search(r"20\d{2}", text):
        return True
    if _CATEGORY_DATE_IN_TEXT_RE.search(text):
        return True
    if _CATEGORY_DATETIME_RE.search(text):
        return True
    if _CATEGORY_COMPACT_DATE_RE.fullmatch(text.replace(" ", "")):
        return True
    return False
