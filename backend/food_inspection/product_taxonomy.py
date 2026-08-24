"""标准小类与建议大类：许可目录 + 食用农产品 + 餐饮具等。"""

from __future__ import annotations

import re
from functools import lru_cache

from food_inspection.product_license_catalog import (
    LICENSE_MAJOR_CATEGORIES,
    LICENSE_SUBCLASS_TO_MAJOR,
    LICENSE_VARIETY_TO_SUBCLASS,
)

# 食用农产品等（不在加工食品许可目录内）
_AGRICULTURAL_SUBCLASS_TO_MAJOR: dict[str, str] = {
    "苹果": "食用农产品",
    "香蕉": "食用农产品",
    "葡萄": "食用农产品",
    "柑橘": "食用农产品",
    "荔枝": "食用农产品",
    "龙眼": "食用农产品",
    "芒果": "食用农产品",
    "西瓜": "食用农产品",
    "梨": "食用农产品",
    "桃": "食用农产品",
    "草莓": "食用农产品",
    "猕猴桃": "食用农产品",
    "火龙果": "食用农产品",
    "柠檬": "食用农产品",
    "橙子": "食用农产品",
    "柚子": "食用农产品",
    "樱桃": "食用农产品",
    "蓝莓": "食用农产品",
    "杨梅": "食用农产品",
    "枇杷": "食用农产品",
    "柿子": "食用农产品",
    "石榴": "食用农产品",
    "哈密瓜": "食用农产品",
    "甜瓜": "食用农产品",
    "白菜": "食用农产品",
    "大白菜": "食用农产品",
    "菠菜": "食用农产品",
    "黄瓜": "食用农产品",
    "西红柿": "食用农产品",
    "土豆": "食用农产品",
    "生姜": "食用农产品",
    "豇豆": "食用农产品",
    "胡萝卜": "食用农产品",
    "白萝卜": "食用农产品",
    "茄子": "食用农产品",
    "芹菜": "食用农产品",
    "韭菜": "食用农产品",
    "山药": "食用农产品",
    "甘薯": "食用农产品",
    "大蒜": "食用农产品",
    "洋葱": "食用农产品",
    "油麦菜": "食用农产品",
    "生菜": "食用农产品",
    "莲藕": "食用农产品",
    "辣椒": "食用农产品",
    "猪肉": "食用农产品",
    "猪五花肉": "食用农产品",
    "牛肉": "食用农产品",
    "羊肉": "食用农产品",
    "鸡肉": "食用农产品",
    "鸭肉": "食用农产品",
    "鸡蛋": "食用农产品",
    "鸭蛋": "食用农产品",
    "鹌鹑蛋": "食用农产品",
    "鲫鱼": "食用农产品",
    "草鱼": "食用农产品",
    "鲈鱼": "食用农产品",
    "虾": "食用农产品",
    "蟹": "食用农产品",
}

# 餐饮具 / 机构 / 抽检项目
_MISC_SUBCLASS_TO_MAJOR: dict[str, str] = {
    "碗": "餐饮具",
    "复用餐饮具": "餐饮具",
    "阴离子合成洗涤剂": "餐饮具",
    "机构主体": "非食品经营主体",
    "二氧化硫残留量": "其他",
    "苯甲酸及其钠盐": "其他",
    "山梨酸及其钾盐": "其他",
    "脱氢乙酸及其钠盐": "其他",
    "氯氟氰菊酯和高效氯氟氰菊酯": "其他",
}

# 小类 → 建议大类（许可目录优先，再叠加农产品等）
SUBCLASS_TO_MAJOR: dict[str, str] = {
    **LICENSE_SUBCLASS_TO_MAJOR,
    **_AGRICULTURAL_SUBCLASS_TO_MAJOR,
    **_MISC_SUBCLASS_TO_MAJOR,
}

# 别名 → 标准小类（许可目录品种名 + 常用简称）
SUBCLASS_SYNONYMS: dict[str, str] = {
    "马铃薯": "土豆",
    "番茄": "西红柿",
    "地瓜": "甘薯",
    "红薯": "甘薯",
    "番薯": "甘薯",
    "长豆": "豇豆",
    "长豇豆": "豇豆",
    "豆角": "豇豆",
    "沃柑": "柑橘",
    "砂糖橘": "柑橘",
    "沙糖桔": "柑橘",
    "沙糖橘": "柑橘",
    "丑橘": "柑橘",
    "丑桔": "柑橘",
    "粑粑柑": "柑橘",
    "五常大米": "大米",
    "东北大米": "大米",
    "五花肉": "猪五花肉",
    "猪瘦肉": "猪肉",
    "猪后腿肉": "猪肉",
    "羊后腿肉": "羊肉",
    "羊瘦肉": "羊肉",
    "牛瘦肉": "牛肉",
    "牛后腿肉": "牛肉",
    "普通白菜": "白菜",
    "圆白菜": "白菜",
    "干桂圆": "桂圆",
    "桂圆干": "桂圆",
    "桂圆肉": "桂圆",
    "大姜": "生姜",
    "山东姜": "生姜",
    "老姜": "生姜",
    "姜": "生姜",
    "马铃薯薯片": "膨化食品",
    "纯切薯片": "膨化食品",
    "夹心硬糖": "糖果",
    "牛奶硬糖": "糖果",
    "面粉": "小麦粉",
    "饮用天然矿泉水": "包装饮用水",
    "饮用纯净水": "包装饮用水",
    "饮用天然水": "包装饮用水",
    "天然矿泉水": "包装饮用水",
    "纯净水": "包装饮用水",
    "包装饮用水": "包装饮用水",
    "煎炸过程用油": "食用植物油",
    "调和油": "食用植物油",
}

# 品种明细 + 别名 → 许可目录小类（按名称长度降序匹配）
_VARIETY_TO_SUBCLASS: dict[str, str] = {
    **LICENSE_VARIETY_TO_SUBCLASS,
    **{k: v for k, v in SUBCLASS_SYNONYMS.items() if v in SUBCLASS_TO_MAJOR},
    **{k: k for k in _AGRICULTURAL_SUBCLASS_TO_MAJOR},
}

_VARIETY_KEYWORDS: tuple[tuple[str, str], ...] = tuple(
    sorted(_VARIETY_TO_SUBCLASS.items(), key=lambda x: len(x[0]), reverse=True)
)

# 关键词推断小类（兜底）
_SUBCLASS_INFER_SPECS: tuple[tuple[str, str], ...] = (
    (r"薯片|膨化|锅巴|虾条|仙贝|米花", "膨化食品"),
    (r"硬糖|酥糖|奶糖|软糖|夹心糖", "糖果"),
    (r"巧克力", "巧克力及巧克力制品"),
    (r"饼干|威化|曲奇", "饼干"),
    (r"蛋糕|面包|月饼|糕点|桃酥", "热加工糕点"),
    (r"火锅底料|火锅蘸料", "调味料"),
    (r"猪瘦肉|猪后腿肉|猪五花肉|猪肉", "猪肉"),
    (r"羊后腿肉|羊瘦肉|羊肉", "羊肉"),
    (r"牛瘦肉|牛后腿肉|牛肉", "牛肉"),
    (r"鸡肉", "鸡肉"),
    (r"鸭肉", "鸭肉"),
    (r"金针菇|香菇|木耳", "食用菌制品"),
    (r"榨菜|泡菜|酱腌菜", "酱腌菜"),
    (r"火腿|香肠|腊肉|肉脯|肉松", "热加工熟肉制品"),
    (r"皮蛋|咸蛋|卤蛋", "蛋制品"),
    (r"酱油", "酱油"),
    (r"食醋", "食醋"),
    (r"蚝油|鸡精|味精", "调味料"),
    (r"纯牛奶|酸奶|巴氏杀菌", "液体乳"),
    (r"奶粉|乳粉", "乳粉"),
    (r"饮用水|矿泉水", "包装饮用水"),
    (r"果汁|果蔬汁", "果蔬汁类及其饮料"),
    (r"茶饮料|奶茶", "茶类饮料"),
    (r"可乐|汽水", "碳酸饮料（汽水）"),
    (r"啤酒", "啤酒"),
    (r"白酒", "白酒"),
    (r"葡萄酒", "葡萄酒及果酒"),
    (r"黄酒", "黄酒"),
    (r"冰淇淋|雪糕", "冷冻饮品"),
    (r"速冻饺子|速冻汤圆|速冻包子", "速冻面米制品"),
    (r"方便面", "方便面"),
    (r"大米|粳米|籼米", "大米"),
    (r"挂面|面条|米粉|米线", "挂面"),
    (r"花生油|菜籽油|大豆油|玉米油|植物油", "食用植物油"),
    (r"豆腐|豆干|腐竹|腐乳", "豆制品"),
    (r"鱼片|鱿鱼|烤虾|海带|紫菜", "熟制水产品"),
    (r"花生|瓜子|核桃|腰果|开心果", "炒货食品及坚果制品"),
    (r"葡萄干|话梅|桂圆干|红枣", "水果制品"),
    (r"粉丝|粉条|粉皮", "淀粉及淀粉制品"),
    (r"蜂蜜", "蜂蜜"),
    (r"茶叶|绿茶|红茶|普洱", "茶叶"),
    (r"碗|餐盘|骨碟|料碗|蘸料碟", "碗"),
)

_SUBCLASS_INFER_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat), sub) for pat, sub in _SUBCLASS_INFER_SPECS
)

_MAJOR_INFER_SPECS: tuple[tuple[str, str], ...] = tuple(
    (rf"(?:{re.escape(major)})", major) for major in LICENSE_MAJOR_CATEGORIES
) + (
    (r"食用农产品|农产品|生鲜|鲜鸡|鲜鸭|鲜蛋", "食用农产品"),
    (r"餐饮具|洗涤剂|餐盘|骨碟", "餐饮具"),
)

_MAJOR_INFER_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat), major) for pat, major in _MAJOR_INFER_SPECS
)


@lru_cache(maxsize=200_000)
def resolve_major_category(subclass: str, original: str = "") -> tuple[str, str]:
    """根据标准小类（及原名回退）解析建议大类。"""
    if subclass in SUBCLASS_TO_MAJOR:
        major = SUBCLASS_TO_MAJOR[subclass]
        return major, f"小类映射→{major}"

    for text in (subclass, original):
        if not text:
            continue
        for pattern, major in _MAJOR_INFER_RULES:
            if pattern.search(text):
                return major, f"关键词推断大类→{major}"

    return "其他", "未匹配大类规则"


def _match_variety_keyword(stripped: str) -> tuple[str, str] | None:
    if stripped in _VARIETY_TO_SUBCLASS:
        target = _VARIETY_TO_SUBCLASS[stripped]
        if target == stripped:
            return target, "标准小类"
        return target, f"品种目录→{target}"

    for keyword, target in _VARIETY_KEYWORDS:
        if stripped == keyword:
            return target, f"品种目录→{target}"
        if stripped.endswith(keyword) and len(stripped) > len(keyword):
            prefix = stripped[: -len(keyword)]
            if 0 < len(prefix) <= 12:
                return target, f"去修饰→{target}"

    return None


def match_standard_subclass(stripped: str, *, original: str = "") -> tuple[str, str] | None:
    """将剥离后的文本匹配为标准小类（许可目录品种名优先）。"""
    if not stripped:
        return None

    hit = _match_variety_keyword(stripped)
    if hit:
        return hit

    for pattern, subclass in _SUBCLASS_INFER_RULES:
        if pattern.search(stripped):
            return subclass, f"关键词→{subclass}"

    for pattern, subclass in _SUBCLASS_INFER_RULES:
        if original and pattern.search(original):
            return subclass, f"原名关键词→{subclass}"

    return None
