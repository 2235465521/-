"""中文查询词切分（离线、无第三方依赖）。

把「储能预制舱」这类连续复合词拆成可独立检索的子词，用于扩大召回。
仅处理纯中文连续串；标准号、英文、带标点的输入保持原样。
"""
from __future__ import annotations

import re

# 领域高频词，命中即作为切分边界；可按业务词库扩充
DOMAIN_TERMS = (
    "预制舱", "储能", "锂离子", "锂电池", "电池", "集装箱", "光伏", "风电",
    "食品安全", "化妆品", "医疗器械", "电动汽车", "充电桩", "信息安全",
    "人工智能", "大数据", "机器人", "坚果", "家具", "建材", "预制", "舱体",
)
_GENERIC_STOP = {
    "技术", "规范", "标准", "要求", "方法", "规程", "指南", "条件",
    "通用", "安全", "部分", "测定", "试验", "系统", "设备",
}
_MIN_LEN = 4
_MAX_TERMS = 2


def split_chinese_phrase(text: str) -> list[str]:
    """返回用于扩展召回的子词；无词表命中时退化为首尾 2 字切分。"""
    s = re.sub(r"\s+", "", text or "")
    if len(s) < _MIN_LEN or not re.fullmatch(r"[\u4e00-\u9fff]+", s):
        return []
    hits: list[str] = []
    for term in DOMAIN_TERMS:
        if term in s and term != s and term not in hits and term not in _GENERIC_STOP:
            hits.append(term)
        if len(hits) >= _MAX_TERMS:
            break
    if not hits:
        head, tail = s[:2], s[-2:]
        hits = [head, tail] if head != tail else [head]
    return [h for h in hits if len(h) >= 2][:_MAX_TERMS]
