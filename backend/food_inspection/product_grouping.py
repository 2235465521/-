"""产品名归类：从原始品名推导建议归类（供导出核查，不直接写库）。"""

from __future__ import annotations

import re
from functools import lru_cache

from food_inspection.parser.fields import PROVINCE_NAMES
from food_inspection.product_name_strip import (
    compact_product_name,
    is_institution_name,
    strip_for_classification,
)
from food_inspection.product_taxonomy import (
    match_standard_subclass,
    resolve_major_category,
)

# 产地 / 来源前缀（按长度降序匹配）
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
            "云南",
            "山东",
            "四川",
            "广东",
            "海南",
            "福建",
            "陕西",
            "甘肃",
        },
        key=len,
        reverse=True,
    )
)

_QUALITY_PREFIXES: tuple[str, ...] = (
    "精品",
    "特级",
    "一级",
    "优选",
    "优质",
    "新鲜",
    "鲜",
    "散称",
    "散装",
    "称重",
    "包装",
    "有机",
    "绿色",
    "无公害",
)

_FORM_PREFIXES: tuple[str, ...] = ()  # 鲜/干不再统一剥离，生鲜与干货分开归类

# 干货标准小类（带「干」前缀或本身为干制品类）
_DRIED_SUBCLASS_NAMES: frozenset[str] = frozenset(
    {
        "干木耳",
        "干海带",
        "干菠菜",
        "干香菇",
        "干黄花菜",
        "干豆角",
        "干笋",
        "桂圆",
        "桂圆干",
        "干桂圆",
    }
)

# 与干货对应的生鲜/湿品（名称不得跨形态合并）
_FRESH_DRIED_PAIRS: tuple[tuple[str, str], ...] = (
    ("木耳", "干木耳"),
    ("海带", "干海带"),
    ("菠菜", "干菠菜"),
    ("龙眼", "桂圆"),
    ("桂圆", "龙眼"),
)

# 饮用水统称
_DRINKING_WATER_ALIASES: frozenset[str] = frozenset(
    {
        "饮用天然矿泉水",
        "饮用纯净水",
        "饮用天然水",
        "饮用水",
        "天然矿泉水",
        "纯净水",
        "包装饮用水",
        "瓶装饮用水",
    }
)

# 火锅底料统称（各品牌/地域风味均并入「火锅底料」）
_HOTPOT_BASE_ALIASES: frozenset[str] = frozenset(
    {
        "牛油火锅店",
        "老火锅底料",
        "重庆火锅底料",
        "四川火锅底料",
        "清汤火锅底料",
        "麻辣火锅底料",
        "牛油火锅底料",
        "番茄火锅底料",
        "菌汤火锅底料",
        "火锅底料",
    }
)

# 畜肉部位 → 标准肉品小类（不再单独保留「后腿肉」「瘦肉」等小类）
_MEAT_CUT_TO_MEAT: tuple[tuple[str, str], ...] = (
    ("猪瘦肉", "猪肉"),
    ("猪后腿肉", "猪肉"),
    ("羊后腿肉", "羊肉"),
    ("羊瘦肉", "羊肉"),
    ("牛瘦肉", "牛肉"),
    ("牛后腿肉", "牛肉"),
    ("鸡瘦肉", "鸡肉"),
    ("鸭瘦肉", "鸭肉"),
)

# 括号内仅描述鲜品/原料（增强规则用）
_FRESH_PAREN_MARKERS: frozenset[str] = frozenset(
    {"鲜", "鲜品", "生鲜", "新鲜", "鲜食用菌", "鲜蛋"}
)

# 含以下词视为加工/复配食品，不做跨品类同义词合并
_PROCESSED_MARKERS: tuple[str, ...] = (
    "八宝粥",
    "粥",
    "饼干",
    "蛋糕",
    "面包",
    "方便面",
    "饮料",
    "啤酒",
    "白酒",
    "葡萄酒",
    "酱油",
    "食醋",
    "陈醋",
    "料酒",
    "调和油",
    "营养",
    "夹心",
    "罐头",
    "火腿肠",
    "肉制品",
    "调味品",
    "酱料",
    "火锅底料",
    "速冻",
    "冷冻",
    "预制",
)

# 生鲜/原料同义词 → 标准小类名（不含龙眼/桂圆互并）
_PRODUCT_SYNONYMS: dict[str, str] = {
    "大姜": "生姜",
    "山东姜": "生姜",
    "山东大姜": "生姜",
    "老姜": "生姜",
    "仔姜": "生姜",
    "小黄姜": "生姜",
    "泥姜": "生姜",
    "本地姜": "生姜",
    "姜": "生姜",
    "番茄": "西红柿",
    "马铃薯": "土豆",
    "地瓜": "甘薯",
    "红薯": "甘薯",
    "番薯": "甘薯",
    "长豆": "豇豆",
    "长豇豆": "豇豆",
    "豆角": "豇豆",
    "鸡蛋芒": "芒果",
    "沃柑": "柑橘",
    "砂糖橘": "柑橘",
    "沙糖桔": "柑橘",
    "沙糖橘": "柑橘",
    "粑粑柑": "柑橘",
    "丑橘": "柑橘",
    "丑桔": "柑橘",
    "五常大米": "大米",
    "东北大米": "大米",
    "长粒香米": "大米",
    "五花肉": "猪五花肉",
    "猪五花肉": "猪五花肉",
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
}

# 小类：名称中含以下词且非加工食品时，归到对应标准小类
_SUBCLASS_KEYWORD_RULES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [
            ("阴离子合成洗涤剂", "阴离子合成洗涤剂"),
            ("氯氟氰菊酯和高效氯氟氰菊酯", "氯氟氰菊酯和高效氯氟氰菊酯"),
            ("高效氯氟氰菊酯", "氯氟氰菊酯和高效氯氟氰菊酯"),
            ("氯氟氰菊酯", "氯氟氰菊酯和高效氯氟氰菊酯"),
            ("脱氢乙酸及其钠盐", "脱氢乙酸及其钠盐"),
            ("脱氢乙酸", "脱氢乙酸及其钠盐"),
            ("苯甲酸及其钠盐", "苯甲酸及其钠盐"),
            ("苯甲酸", "苯甲酸及其钠盐"),
            ("山梨酸及其钾盐", "山梨酸及其钾盐"),
            ("山梨酸", "山梨酸及其钾盐"),
            ("二氧化硫残留量", "二氧化硫残留量"),
            ("二氧化硫残留", "二氧化硫残留量"),
            ("食用植物调和油", "食用植物调和油"),
            ("煎炸过程用油", "煎炸过程用油"),
            ("阴离子合成洗涤剂", "阴离子合成洗涤剂"),
            ("纯牛奶", "纯牛奶"),
            ("纯羊奶", "纯羊奶"),
            ("花生油", "花生油"),
            ("菜籽油", "菜籽油"),
            ("大豆油", "大豆油"),
            ("玉米油", "玉米油"),
            ("调和油", "食用植物调和油"),
            ("长豇豆", "豇豆"),
            ("西红柿", "西红柿"),
            ("马铃薯", "土豆"),
            ("龙眼", "龙眼"),
            ("桂圆", "桂圆"),
            ("生姜", "生姜"),
            ("白芷", "白芷"),
            ("豇豆", "豇豆"),
            ("土豆", "土豆"),
            ("甘薯", "甘薯"),
            ("芒果", "芒果"),
            ("香蕉", "香蕉"),
            ("苹果", "苹果"),
            ("葡萄", "葡萄"),
            ("山药", "山药"),
            ("茄子", "茄子"),
            ("黄瓜", "黄瓜"),
            ("芹菜", "芹菜"),
            ("韭菜", "韭菜"),
            ("大白菜", "大白菜"),
            ("白萝卜", "白萝卜"),
            ("胡萝卜", "胡萝卜"),
            ("洋葱", "洋葱"),
            ("大蒜", "大蒜"),
            ("猪肉", "猪肉"),
            ("牛肉", "牛肉"),
            ("羊肉", "羊肉"),
            ("鸡肉", "鸡肉"),
            ("鸭肉", "鸭肉"),
            ("鸡蛋", "鸡蛋"),
            ("鸭蛋", "鸭蛋"),
            ("鹌鹑蛋", "鹌鹑蛋"),
            ("馒头", "馒头"),
            ("面条", "面条"),
            ("米粉", "米粉"),
            ("米线", "米线"),
            ("饺子", "饺子"),
            ("包子", "包子"),
            ("白酒", "白酒"),
            ("啤酒", "啤酒"),
            ("矿泉水", "矿泉水"),
            ("饮用水", "饮用水"),
            ("大米", "大米"),
            ("沃柑", "柑橘"),
            ("砂糖橘", "柑橘"),
            ("油麦菜", "油麦菜"),
            ("白菜", "白菜"),
            ("荔枝", "荔枝"),
            ("木耳", "木耳"),
            ("干木耳", "干木耳"),
            ("海带", "海带"),
            ("干海带", "干海带"),
            ("菠菜", "菠菜"),
            ("干菠菜", "干菠菜"),
            ("火锅底料", "火锅底料"),
            ("猪五花肉", "猪五花肉"),
        ],
        key=lambda x: len(x[0]),
        reverse=True,
    )
)

# 小类：尾部匹配的标准品名（按长度降序）
_SUBCLASS_CORE_NAMES: tuple[str, ...] = tuple(
    sorted(
        {
            "阴离子合成洗涤剂", "氯氟氰菊酯和高效氯氟氰菊酯", "脱氢乙酸及其钠盐",
            "苯甲酸及其钠盐", "山梨酸及其钾盐", "二氧化硫残留量", "食用植物调和油",
            "煎炸过程用油", "纯牛奶", "纯羊奶", "花生油", "菜籽油", "大豆油", "玉米油",
            "五常大米", "大米", "桂圆", "龙眼", "生姜", "白芷", "豇豆", "长豇豆",
            "西红柿", "番茄", "土豆", "甘薯", "芒果", "香蕉", "苹果", "葡萄", "山药",
            "茄子", "黄瓜", "芹菜", "韭菜", "白菜", "大白菜", "白萝卜", "胡萝卜", "洋葱",
            "大蒜", "猪肉", "牛肉", "羊肉", "鸡肉", "鸭肉", "鸡蛋", "鸭蛋", "馒头",
            "面条", "米粉", "米线", "饺子", "包子", "白酒", "啤酒", "饮用水",
            "碗", "复用餐饮具", "柑橘", "沃柑", "砂糖橘", "油麦菜", "豇豆", "长豆",
            "木耳", "干木耳", "海带", "干海带", "菠菜", "干菠菜", "荔枝", "火锅底料",
            "猪五花肉",
        },
        key=len,
        reverse=True,
    )
)

_EXTRA_STRIP_PREFIXES: tuple[str, ...] = (
    "精品", "特级", "一级", "优选", "优质", "新鲜", "鲜", "散称", "散装", "称重",
    "包装", "有机", "绿色", "本地", "当季", "时令", "精选", "特选", "普通", "常规",
)

_EXTRA_STRIP_SUFFIXES: tuple[str, ...] = (
    "散装称重", "散称称重", "计量称重", "散装", "散称", "称重", "（散装）", "(散装)",
)

_BRAND_NOISE_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fa5]{1,8}(?=[\u4e00-\u9fa5]{2,})")
_TRAILING_NOISE_RE = re.compile(r"[\dA-Za-z号级型款装盒袋瓶包罐条只个]+$")

# 建议归类的展示名（group_key → 人工友好名称）
_GROUP_DISPLAY_NAMES: dict[str, str] = {
    "桂圆": "桂圆",
    "龙眼": "龙眼",
    "生姜": "生姜",
    "白芷": "白芷",
    "西红柿": "西红柿",
    "土豆": "土豆",
    "豇豆": "豇豆",
    "芒果": "芒果",
    "饮用水": "饮用水",
    "火锅底料": "火锅底料",
    "猪五花肉": "猪五花肉",
    "白菜": "白菜",
    "荔枝": "荔枝",
}

_PAREN_CONTENT_RE = re.compile(r"[（(]([^）)]*)[）)]")
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_ORIGIN_PREFIX_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in _ORIGIN_PREFIXES) + r")"
)


def _compact(name: str) -> str:
    return compact_product_name(name)


def _is_processed(name: str) -> bool:
    return any(marker in name for marker in _PROCESSED_MARKERS)


def _strip_prefixes(name: str, prefixes: tuple[str, ...]) -> tuple[str, list[str]]:
    steps: list[str] = []
    current = name
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if current.startswith(prefix) and len(current) > len(prefix) + 1:
                current = current[len(prefix) :]
                steps.append(f"去前缀「{prefix}」")
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


def _fresh_dried_merge_blocked(candidate: str, target: str) -> bool:
    """禁止生鲜与干货、龙眼与桂圆跨形态合并。"""
    for fresh, dried in _FRESH_DRIED_PAIRS:
        if (fresh in candidate and dried == target) or (dried in candidate and fresh == target):
            return True
    if candidate.startswith("干") and not target.startswith("干"):
        base = candidate[1:]
        if base == target or target in base:
            return True
    if target.startswith("干") and not candidate.startswith("干"):
        base = target[1:]
        if base == candidate or candidate in base:
            return True
    return False


def _resolve_dried_fresh_subclass(name: str) -> tuple[str, str] | None:
    """木耳/干木耳、海带/干海带、菠菜/干菠菜等：鲜干分开。"""
    if name.startswith("干") and len(name) > 1:
        tail = name[1:]
        for fresh in ("木耳", "海带", "菠菜", "香菇", "黄花菜", "豆角", "笋"):
            if tail == fresh or tail.endswith(fresh):
                return f"干{fresh}", f"干货→干{fresh}"
    for fresh in ("木耳", "海带", "菠菜"):
        if name == fresh or (name.endswith(fresh) and not name.startswith("干")):
            if "干" not in name.replace(fresh, ""):
                return fresh, f"生鲜/湿品→{fresh}"
    return None


def _resolve_longan_guiyuan(name: str) -> tuple[str, str] | None:
    """桂圆与龙眼分开；并存时归桂圆，仅龙眼时归龙眼。"""
    if _is_processed(name):
        return None
    has_guiyuan = "桂圆" in name
    has_longan = "龙眼" in name
    if has_guiyuan and has_longan:
        return "桂圆", "桂圆+龙眼并存→桂圆"
    if has_guiyuan:
        return "桂圆", "桂圆（干龙眼）"
    if has_longan:
        return "龙眼", "龙眼（鲜品）"
    return None


def _resolve_drinking_water(name: str) -> tuple[str, str] | None:
    if name in _DRINKING_WATER_ALIASES:
        return "包装饮用水", "包装饮用水"
    if "饮用" in name and any(token in name for token in ("矿泉水", "纯净水", "天然水", "饮用水")):
        return "包装饮用水", "包装饮用水"
    return None


def _resolve_hotpot_base(name: str) -> tuple[str, str] | None:
    if name in _HOTPOT_BASE_ALIASES:
        return "调味料", "火锅底料→调味料"
    if "火锅底料" in name:
        return "调味料", "火锅底料→调味料"
    if name.endswith("火锅店") and "火锅" in name:
        return "调味料", "火锅底料→调味料"
    return None


def _resolve_meat_cuts(name: str, raw: str) -> tuple[str, str] | None:
    compact = name
    if compact in ("五花肉", "猪五花肉"):
        return "猪五花肉", "五花肉=猪五花肉"

    for cut, meat in _MEAT_CUT_TO_MEAT:
        if compact == cut:
            return meat, f"{cut}→{meat}"

    if "后腿肉" in compact or "后腿肉" in raw:
        for animal, meat in (("猪", "猪肉"), ("羊", "羊肉"), ("牛", "牛肉")):
            token = f"{animal}后腿肉"
            if compact == token or token in raw:
                return meat, f"{token}→{meat}"
            if (
                animal in compact
                and compact.endswith("后腿肉")
                and len(compact) <= len(animal) + 4
            ):
                return meat, f"后腿肉→{meat}"
            if f"（{animal}肉）" in raw or f"({animal}肉)" in raw:
                return meat, f"（{animal}肉）后腿肉→{meat}"

        if compact == "后腿肉" or compact.endswith("后腿肉"):
            if "羊" in compact or "羔羊" in raw:
                return "羊肉", "后腿肉→羊肉"
            if "牛" in compact:
                return "牛肉", "后腿肉→牛肉"
            if "猪" in compact or "猪肉" in raw:
                return "猪肉", "后腿肉→猪肉"
            return "猪肉", "后腿肉→猪肉"

    if "瘦肉" in compact and compact not in ("猪肉", "羊肉", "牛肉", "鸡肉", "鸭肉"):
        for animal, meat in (("猪", "猪肉"), ("羊", "羊肉"), ("牛", "牛肉")):
            token = f"{animal}瘦肉"
            if compact == token or (animal in compact and "瘦肉" in compact):
                return meat, f"{token}→{meat}"
        if compact == "瘦肉" or (
            compact.endswith("瘦肉")
            and not any(a in compact for a in ("猪", "羊", "牛", "鸡", "鸭"))
        ):
            if "羊" in compact or "羔羊" in raw:
                return "羊肉", "瘦肉→羊肉"
            if "牛" in compact:
                return "牛肉", "瘦肉→牛肉"
            return "猪肉", "瘦肉→猪肉"

    return None


def _resolve_variety_fruit(name: str) -> tuple[str, str] | None:
    if name.endswith("荔枝") and name != "荔枝":
        return "荔枝", f"品种归并→荔枝"
    if name.endswith("葡萄") and name != "葡萄" and len(name) <= 10:
        return "葡萄", "品种归并→葡萄"
    return None


def _apply_enhanced_subclass_rules(raw: str, name: str) -> tuple[str, str] | None:
    """用户确认的增强归类规则（优先于通用规则）。"""
    for resolver in (
        _resolve_longan_guiyuan,
        _resolve_dried_fresh_subclass,
        _resolve_drinking_water,
        _resolve_hotpot_base,
        lambda n: _resolve_meat_cuts(n, raw),
        _resolve_variety_fruit,
    ):
        result = resolver(name)
        if result:
            return result
    return None


def _strip_form_prefix(name: str) -> tuple[str, list[str]]:
    return name, []


def _apply_synonym(name: str, *, allow: bool) -> tuple[str, list[str]]:
    if not allow:
        return name, []
    if name in _PRODUCT_SYNONYMS:
        target = _PRODUCT_SYNONYMS[name]
        return target, [f"同义词→{target}"]
    return name, []


def _has_form_conflict(original: str, core: str) -> bool:
    """干货/加工品不与生鲜简单合并。"""
    if "干" in original and "干" not in core and len(original) <= len(core) + 2:
        return True
    return _is_processed(original) and core not in original


def propose_product_group(name: str) -> tuple[str, str, bool]:
    """
    建议大类：按食品生产许可分类目录，由标准小类映射得出。
    返回 (建议大类, 说明, 是否建议人工复核)。
    """
    subclass, sub_note, sub_review = propose_product_subclass(name)
    raw = _compact(name)
    if not subclass:
        return "", sub_note or "空名称", True
    if subclass == "机构主体":
        return "非食品经营主体", sub_note, False

    major, major_note = resolve_major_category(subclass, raw)
    note = sub_note
    if major_note:
        note = f"{note}；{major_note}" if note else major_note
    return major, note, sub_review


@lru_cache(maxsize=200_000)
def cached_propose_product_group(name: str) -> tuple[str, str, bool]:
    return propose_product_group(name)


def _strip_extra_affixes(name: str) -> tuple[str, list[str]]:
    steps: list[str] = []
    current = name
    for suffix in _EXTRA_STRIP_SUFFIXES:
        if current.endswith(suffix) and len(current) > len(suffix) + 1:
            current = current[: -len(suffix)]
            steps.append(f"去后缀「{suffix}」")
    current, prefix_steps = _strip_prefixes(current, _EXTRA_STRIP_PREFIXES)
    steps.extend(prefix_steps)
    current = _TRAILING_NOISE_RE.sub("", current).strip()
    return current or name, steps


def _match_subclass_core(name: str) -> tuple[str, str] | None:
    enhanced = _apply_enhanced_subclass_rules(name, name)
    if enhanced:
        return enhanced
    if name in _PRODUCT_SYNONYMS:
        target = _PRODUCT_SYNONYMS[name]
        return target, f"同义词→{target}"
    for core in _SUBCLASS_CORE_NAMES:
        if name == core:
            return core, "标准小类"
        if name.endswith(core) and len(name) > len(core):
            prefix = name[: -len(core)]
            if 0 < len(prefix) <= 12 and not _fresh_dried_merge_blocked(name, core):
                return core, f"去品牌/前缀→{core}"
    for keyword, target in _SUBCLASS_KEYWORD_RULES:
        if name == keyword:
            return target, f"标准小类→{target}"
        if name.endswith(keyword) and len(name) > len(keyword):
            prefix = name[: -len(keyword)]
            if 0 < len(prefix) <= 12 and not _fresh_dried_merge_blocked(name, target):
                return target, f"尾部「{keyword}」→{target}"
        if keyword in name and len(name) <= len(keyword) + 4:
            if keyword == "二氧化硫" and "残留" not in name:
                continue
            return target, f"关键词「{keyword}」→{target}"
    return None


def propose_product_subclass(name: str) -> tuple[str, str, bool]:
    """
    建议小类：剥离品牌/口味/形态等干扰项后，合并为最基础标准品类名。
    返回 (建议小类, 说明, 是否建议人工复核)。
    """
    raw = _compact(name)
    if not raw:
        return "", "空名称", True

    if is_institution_name(raw):
        return "机构主体", "非食品经营主体", False

    steps: list[str] = []
    stripped, strip_steps = strip_for_classification(raw)
    if strip_steps:
        steps.extend(strip_steps)

    enhanced = _apply_enhanced_subclass_rules(raw, stripped)
    if enhanced:
        target, note = enhanced
        steps.append(note)
        return target, "；".join(steps), False

    match = match_standard_subclass(stripped, original=raw)
    if match:
        target, match_note = match
        steps.append(match_note)
        subclass = target
    else:
        synonym_target, syn_steps = _apply_synonym(stripped, allow=True)
        if syn_steps:
            steps.extend(syn_steps)
            subclass = synonym_target
        else:
            subclass = stripped or raw

    needs_review = False
    if subclass != raw and len(subclass) < 2:
        needs_review = True
        steps.append("⚠小类过短")

    note = "；".join(steps) if steps else "保持原名"
    return subclass, note, needs_review


@lru_cache(maxsize=200_000)
def cached_propose_product_subclass(name: str) -> tuple[str, str, bool]:
    return propose_product_subclass(name)


def merge_singleton_subclass(
    subclass: str,
    original_name: str,
    anchor_set: set[str],
) -> tuple[str, str]:
    """
    仅 1 个原始品名的细分类，尝试并入已有「多样品」小类。
    返回 (合并后小类, 说明)。
    """
    candidates: list[str] = []
    for value in (subclass, _compact(original_name)):
        if value and value not in candidates:
            candidates.append(value)

    if subclass.startswith("即食") or any(c.startswith("即食") for c in candidates):
        return subclass, ""

    for candidate in candidates:
        best_suffix = ""
        best_prefix_len = len(candidate)
        for start in range(len(candidate) - 1):
            suffix = candidate[start:]
            if len(suffix) < 2 or suffix not in anchor_set:
                continue
            if start <= 8 and start < best_prefix_len:
                best_suffix = suffix
                best_prefix_len = start
        if best_suffix:
            if _fresh_dried_merge_blocked(candidate, best_suffix):
                continue
            return best_suffix, f"单样品并入多样品小类「{best_suffix}」"

        for prefix_len in range(2, 5):
            if len(candidate) <= prefix_len + 1:
                continue
            rest = candidate[prefix_len:]
            if rest in anchor_set and rest != candidate:
                if _fresh_dried_merge_blocked(candidate, rest):
                    continue
                return rest, f"单样品去前缀并入「{rest}」"

    return subclass, ""


def build_subclass_merge_map(
    subclass_groups: dict[str, list[dict]],
    *,
    min_anchor_members: int = 2,
) -> dict[str, tuple[str, str]]:
    """为「仅 1 个原始品名」的小类生成向上合并映射。"""
    anchor_set = {
        name
        for name, members in subclass_groups.items()
        if len(members) >= min_anchor_members
    }
    merge_map: dict[str, tuple[str, str]] = {}

    for name, members in subclass_groups.items():
        if len(members) != 1:
            continue
        original = members[0].get("food_name") or ""
        merged, note = merge_singleton_subclass(name, original, anchor_set)
        if merged != name and note:
            merge_map[name] = (merged, note)

    return merge_map
