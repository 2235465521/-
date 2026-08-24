"""判断抽检文件/样品是否属于食品安全范畴，过滤工业品、消防、服装等非食品数据。"""

from __future__ import annotations

import os
import re

from food_inspection.parser.text import _clean
_NON_FOOD_FILE_MARKERS = (
    "工业品质量",
    "工业产品监督",
    "工业产品抽检",
    "工业产品抽查",
    "消防产品",
    "消防器材",
    "消防监督",
    "电动自行车",
    "电动车质量",
    "电动车抽查",
    "学生装",
    "校服抽查",
    "校服质量",
    "服装抽查",
    "服装质量",
    "纺织品抽查",
    "纺织品质量",
    "家用电器",
    "家电抽查",
    "儿童玩具",
    "玩具抽查",
    "成品油",
    "危险化学品",
    "建筑材料",
    "建筑用材",
    "化妆品抽查",
    "药品抽查",
    "机动车检验",
    "汽车尾气",
    "纸制品质量",  # 纸杯/淋膜纸等食品相关包装在 analytics 中单独处理
    "产品质量监督抽查",  # 通用产品质量（非「食品」专项）
    "产品质量抽检",
    "轻工产品",
    "五金产品",
    "电线电缆",
    "燃气器具",
    "灶具抽查",
    "口罩抽查",
    "农资抽查",
    "种子抽查",
    "肥料抽查",
)

_FOOD_FILE_MARKERS = (
    "食品",
    "食用农产品",
    "餐饮食品",
    "餐饮具",
    "食品添加剂",
    "保健食品",
    "学校食堂",
    "食堂食品",
)

# 样品名 / 分类命中 → 单行跳过
_NON_FOOD_PRODUCT_KEYWORDS = (
    "灭火毯",
    "灭火器",
    "消防水带",
    "消防栓",
    "鞭炮",
    "烟花",
    "爆竹",
    "礼花",
    "玻璃水",
    "尿素溶液",
    "车用尿素",
    "尾气净化",
    "净化液",
    "防冻液",
    "制动液",
    "润滑油",
    "电动自行车",
    "电动车",
    "落地扇",
    "电风扇",
    "换气扇",
    "电扇",
    "台扇",
    "塑料购物袋",
    "购物袋",
    "学生装",
    "校服",
    "运动服",
    "工作服",
    "电线电缆",
    "开关插座",
    "插座",
    "插头",
    "燃气灶",
    "热水器",
    "空调",
    "洗衣机",
    "冰箱",
    "电视机",
    "玩具枪",
    "儿童玩具",
    "口罩",
    "卫生巾",
    "纸尿裤",
    "化妆品",
    "农药",
    "种子",
    "肥料",
    # 建材 / 电工 / 化纤
    "聚氯乙烯",
    "绝缘电线",
    "绝缘电缆",
    "PVC-U",
    "PVC管",
    "建筑排水",
    "排水用",
    "聚乙烯丙",
    "丙纶",
    "涤纶",
    "化纤",
    "防水卷材",
    "管材",
    "管件",
    # 非食品塑料杯（食品用碗盘餐饮具抽检保留）
    "航空杯",
    "商务塑杯",
    "塑杯",
    "塑料饮杯",
    "塑料饮",
    "一次性杯",
)

_NON_FOOD_CATEGORIES = frozenset(
    {
        "工业产品",
        "轻工产品",
        "纺织产品",
        "纺织品",
        "服装",
        "家用电器",
        "电子产品",
        "建材产品",
        "消防产品",
        "农资产品",
        "化妆品",
        "药品",
        "机动车",
        "电动车",
        "纸制品",
    }
)


def _compact_text(*parts: str) -> str:
    return re.sub(r"\s+", "", "".join(p for p in parts if p))


def is_non_food_inspection_file(filepath: str) -> bool:
    """路径/文件名语义判断：非食品安全抽检附件则跳过整文件。"""
    if not filepath:
        return False
    compact = _compact_text(os.path.basename(filepath), filepath).replace("\\", "/")
    if any(m.replace(" ", "") in compact for m in _FOOD_FILE_MARKERS):
        return False
    return any(m.replace(" ", "") in compact for m in _NON_FOOD_FILE_MARKERS)


def is_food_product(product: str, category: str = "") -> bool:
    """样品名称与分类语义判断：明显非食品则跳过该行。"""
    name = _compact_text(product)
    cat = _clean(category)
    if not name:
        return False
    if cat in _NON_FOOD_CATEGORIES:
        return False
    if any(k in name for k in _NON_FOOD_PRODUCT_KEYWORDS):
        return False
    # 「产品质量监督抽查」类表偶见空分类 + 工业品名
    if re.search(r"(?:电动|消防|鞭炮|烟花|玻璃水|尿素|校服|学生装|购物袋|落地扇)", name):
        return False
    if re.search(
        r"(?:聚氯乙烯|绝缘电|PVC-?U|建筑排水|聚乙烯丙|丙纶|涤纶|航空杯|商务塑杯|塑杯|化纤)",
        name,
        re.I,
    ):
        return False
    return True
