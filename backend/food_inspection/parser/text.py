"""文本清洗与表头规范化。"""

from __future__ import annotations

import re
from typing import Any

def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace("／", "/").replace("－", "-").replace("—", "-")
    if text in ("/", "-", "—", "nan", "None", "无", "暂无", "不详", "未知"):
        return ""
    if text.lower() in ("na", "n/a", "null", "none"):
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return re.sub(r"\s+", " ", text)


_COMPANY_HEADER_MARKERS = frozenset(
    {
        "生产企业名称",
        "标称生产企业名称",
        "标识生产企业名称",
        "被抽样单位名称",
        "生产单位",
        "企业名称",
        "单位名称",
    }
)


def _is_consignor_delegate_format(text: str) -> bool:
    compact = text.replace(" ", "")
    return ("委托方" in compact or "委托方:" in compact) and (
        "受托方" in compact or "受托方:" in compact
    )


def split_consignor_delegate_company(value: Any) -> str:
    """从「委托方：…；受托方：…」中提取受托方（无则委托方）名称。"""
    text = _clean(value)
    if not text:
        return ""
    for label in ("受托方：", "受托方:", "委托方：", "委托方:"):
        if label in text:
            part = text.split(label, 1)[-1]
            part = re.split(r"[；;]", part, maxsplit=1)[0]
            return _clean(part)
    return text


def collapse_wrapped_chinese_text(text: str) -> str:
    """去掉 PDF/Excel 单元格换行折叠产生的多余空格。"""
    text = _clean(text)
    if not text:
        return ""
    # 汉字之间的换行空格：批发 部 → 批发部
    text = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", text)
    # 括号内换行：（福 建）→（福建）
    def _collapse_paren(match: re.Match[str]) -> str:
        inner = match.group(0)
        return re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", inner)

    text = re.sub(r"[（(][^）)]*[）)]", _collapse_paren, text)
    # 汉字与左括号之间：南洋 (思乡) → 南洋(思乡)
    text = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[（(])", "", text)
    return text


def normalize_company_name(value: Any) -> str:
    """标准化单位/企业名称，占位符视为空。"""
    text = collapse_wrapped_chinese_text(_clean(value))
    if text in _COMPANY_HEADER_MARKERS:
        return ""
    if _is_consignor_delegate_format(text):
        return split_consignor_delegate_company(text)
    return text


# 产品名细分 → 统计用统称（按长度降序优先精确匹配）
_PRODUCT_CANONICAL: dict[str, str] = {
    "密胺碗": "碗",
    "陶瓷碗": "碗",
    "不锈钢碗": "碗",
    "仿瓷碗": "碗",
    "大碗": "碗",
    "小碗": "碗",
    "饭碗": "碗",
    "汤碗": "碗",
    "菜碗": "碗",
    "骨碗": "碗",
    "面碗": "碗",
    "白碗": "碗",
}

_BOWL_PRODUCT_RE = re.compile(
    r"^(?:密胺|陶瓷|不锈钢|仿瓷|Melamine)?"
    r"(?:大|小|饭|汤|菜|骨|面|白|餐|消毒|粉)?碗"
    r"(?:[（(].*)?$"
)

# 榜单统计：各类碟/碗/筷等复用型餐饮具统一合并
_REUSABLE_TABLEWARE_CANONICAL = "复用餐饮具"
_REUSABLE_TABLEWARE_MARKERS = (
    "复用餐饮具",
    "复用型餐饮具",
    "自消毒餐具",
    "自消毒餐饮具",
    "自消餐饮具",
    "自行消毒餐饮具",
    "自行消毒餐具",
    "集中消毒餐饮具",
    "集中消毒餐具",
    "复用消毒餐饮具",
)
_REUSABLE_TABLEWARE_LOOSE_RE = re.compile(r"复用.{0,6}餐饮具|餐饮具.{0,6}复用")
_STANDALONE_DISINFECTED_TABLEWARE_RE = re.compile(
    r"^(?:套装)?消毒餐具(?:套装)?$"
)

_TRAILING_ENUM_DIGIT = re.compile(r"^(.+?)([1-9]\d{0,2})$")
_SINGLE_CHAR_ENUM_PRODUCTS = frozenset("碗碟盘杯筷勺")
_HOMEMADE_PREFIX_RE = re.compile(r"^自制([\u4e00-\u9fa5].+)$")
_HOMEMADE_SUFFIX_RE = re.compile(r"^([\u4e00-\u9fa5].+?)[（(]自制[)）]$")


def _canonical_homemade_product(compact: str) -> str | None:
    """自制甜馒头 / 甜馒头（自制）等同义归一。"""
    match = _HOMEMADE_PREFIX_RE.match(compact)
    if match:
        core = match.group(1).strip()
        if len(core) >= 2:
            return f"{core}（自制）"
    match = _HOMEMADE_SUFFIX_RE.match(compact)
    if match:
        core = match.group(1).strip()
        if len(core) >= 2:
            return f"{core}（自制）"
    return None


def strip_product_enumeration_suffix(name: str) -> str:
    """花椒1 / 花椒2 → 花椒（去掉同表重复样品的末尾编号）。"""
    text = _clean(name)
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    match = _TRAILING_ENUM_DIGIT.match(compact)
    if not match:
        return text
    head = match.group(1)
    if len(head) < 2:
        if head in _SINGLE_CHAR_ENUM_PRODUCTS:
            return head
        return text
    if head[-1] in "B型号级类种" or re.search(r"[A-Za-z]$", head):
        return text
    return head


def is_reusable_tableware_product_name(value: Any) -> bool:
    """是否为复用型餐饮具（含自消毒/集中消毒等同类表述）。"""
    text = collapse_wrapped_chinese_text(value)
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if "一次性" in compact:
        return False
    if any(marker in compact for marker in _REUSABLE_TABLEWARE_MARKERS):
        return True
    if _REUSABLE_TABLEWARE_LOOSE_RE.search(compact):
        return True
    return bool(_STANDALONE_DISINFECTED_TABLEWARE_RE.fullmatch(compact))


def normalize_product_name(value: Any) -> str:
    """标准化产品名称，合并同类细分品名便于榜单统计。"""
    text = collapse_wrapped_chinese_text(value)
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    if is_reusable_tableware_product_name(compact):
        return _REUSABLE_TABLEWARE_CANONICAL
    homemade = _canonical_homemade_product(compact)
    if homemade:
        return homemade
    if compact in _PRODUCT_CANONICAL:
        return _PRODUCT_CANONICAL[compact]
    compact = strip_product_enumeration_suffix(compact) or compact
    if compact in _PRODUCT_CANONICAL:
        return _PRODUCT_CANONICAL[compact]
    if "碗面" in compact or compact.endswith("碗面"):
        return text
    if compact == "碗":
        return "碗"
    if _BOWL_PRODUCT_RE.fullmatch(compact):
        return "碗"
    if re.search(r"[（(]碗[)）]?$", compact) or compact.startswith(("碗（", "碗(")):
        return "碗"
    if "餐饮具" in compact and "碗" in compact:
        return "碗"
    return collapse_wrapped_chinese_text(text)


_COMPANY_FRAGMENT_ONLY = frozenset({
    "司", "店", "品", "号", "公司", "有限", "限公司", "有限公司", "任公司",
    "厂", "行", "摊", "摊床", "里分公司", "二分公司",
    "单位", "名称", "企业", "生产", "标称", "抽样", "被抽样",
    "抽样编号", "抽样编号为", "样品编号", "序号",
})

_PROVINCE_SHORT_NAMES = frozenset({
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
})

_COMPANY_ENTITY_MARKERS = (
    "公司", "有限", "责任", "集团", "企业", "工厂", "食品", "餐饮", "超市",
    "商店", "商行", "经营部", "便利店", "购物中心", "门市", "批发", "零售",
    "贸易", "商贸", "农贸", "中心", "食堂", "餐厅", "饭店", "合作社",
    "养殖场", "加工厂", "工作室", "个体", "股份", "合伙",
)

_BUSINESS_NAME_SUFFIXES = ("店", "厂", "行", "社", "场", "坊", "铺", "馆", "院", "所", "部", "楼")

_PERSON_NAME_RE = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")

_INSPECTION_AGENCY_RE = re.compile(
    r"检验检测|检测研究院|质检院|检科院|测试中心|测试集团|测试所|计量测试|计量检测|计量院|"
    r"特种设备检测|食品检验|药品检验|食品药品检验|产品质量检验|质量检验|质量监督|"
    r"检验所|检验站|检验中心|检测中心|分析测试|研究院|研究所|"
    r"技术监督|检定所|监督检测|海关|中检联|中检达|中检|华测检测|谱尼测试|广电计量|"
    r"检测技术|检测认证|质量检测|食品安全检测|检测股份|检测集团|"
    r"汇标检测|华鑫检测|检联检测|和泰质量检测|安诺科技|通量检|通量测|"
    r"海关技术|检验检测认证|华测|谱尼|广电计量|拱北海关"
)

# 含「检测/检验」且明显为第三方实验室，而非食品生产经营企业
_INSPECTION_AGENCY_HINT_RE = re.compile(
    r"(?:"
    r"检验站|检验中心|检测所|检测中心|测试中心|测试集团|监督检测所|"
    r"海关|质量计量|计量监督|检测股份|检测集团|检测技术|检测认证|"
    r"食品安全检测|食品药品检验|产品质量检验|质量监督"
    r")"
)


def is_inspection_agency(value: Any) -> bool:
    """检验/检测机构，非被抽检或生产单位。"""
    text = normalize_company_name(value)
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if _INSPECTION_AGENCY_RE.search(compact):
        return True
    if _INSPECTION_AGENCY_HINT_RE.search(compact):
        # 「XX检测有限公司」类实验室；保留含明确生产经营特征词的企业
        business_markers = (
            "超市", "商场", "商店", "商行", "餐饮", "饭店", "餐厅", "食堂",
            "食品厂", "加工厂", "生产", "贸易", "批发", "零售", "农场", "养殖",
        )
        if any(marker in compact for marker in business_markers):
            return False
        if "检测" in compact or "检验" in compact or "测试" in compact:
            return True
    if "有限公司" in compact and any(k in compact for k in ("检", "测", "通量", "质检", "检验")):
        if not any(
            marker in compact
            for marker in ("超市", "商场", "商店", "商行", "餐饮", "饭店", "餐厅", "食堂", "食品厂", "加工厂")
        ):
            return True
    return False


def _is_truncated_company_fragment(compact: str) -> bool:
    """PDF/Excel 列错位产生的公司名残片（如「物科技有限公司」缺前缀）。"""
    if compact.startswith("物科技"):
        return True
    if compact.startswith(("技有限公司", "科有限公司", "份有限公司")):
        return True
    if re.fullmatch(r"[\u4e00-\u9fa5]物科技有限公司", compact):
        return True
    if len(compact) <= 8 and compact.endswith("有限公司") and "公司" in compact[:-4]:
        return True
    return False


def _is_company_suffix_fragment(compact: str) -> bool:
    """「限公司」「里分公司」等 PDF 列错位产生的公司名残片。"""
    if _is_truncated_company_fragment(compact):
        return True
    if compact.endswith("分公司") and len(compact) <= 6:
        return True
    if compact.endswith("公司") and len(compact) <= 4:
        return True
    return False


def _looks_like_person_name(compact: str) -> bool:
    """2~4 个汉字、无企业特征词，多为个体户姓名误作单位名。"""
    if not _PERSON_NAME_RE.fullmatch(compact):
        return False
    if any(marker in compact for marker in _COMPANY_ENTITY_MARKERS):
        return False
    if compact.endswith(_BUSINESS_NAME_SUFFIXES):
        return False
    return True


def is_invalid_company(value: Any) -> bool:
    """占位符、表头碎片、省份名、过短 OCR 残片视为无效单位名。"""
    text = normalize_company_name(value)
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if compact in _COMPANY_FRAGMENT_ONLY:
        return True
    if compact in ("--", "-", "\\", "/"):
        return True
    if compact.startswith("抽样编号"):
        return True
    if compact.endswith("超标") and not any(
        marker in compact
        for marker in ("公司", "有限", "责任", "集团", "企业", "工厂", "店", "商行", "超市", "合作社")
    ):
        return True
    if any(k in compact for k in ("没收违法", "违法所得", "非法财物")):
        return True
    if compact in _PROVINCE_SHORT_NAMES:
        return True
    if _is_company_suffix_fragment(compact):
        return True
    if _looks_like_person_name(compact):
        return True
    if is_inspection_agency(compact):
        return True
    if len(compact) == 1 and compact in "司店品厂行社":
        return True
    if len(compact) <= 2 and not any(marker in compact for marker in _COMPANY_ENTITY_MARKERS):
        return True
    return False


def is_health_food_sheet(headers: list[str]) -> bool:
    """重庆等地保健食品监督抽检表：标称产品名称 + 被抽样单位名称。"""
    normalized = {_normalize_header(h) for h in headers if _clean(h)}
    has_product = bool(
        normalized
        & {"保健食品名称", "标称产品名称", "保健产品名称"}
    )
    has_sampled_unit = any("被抽样单位名称" in h for h in normalized)
    has_maker = bool(
        normalized & {"生产企业名称", "生产企业", "标称生产企业名称"}
    )
    return has_product and has_sampled_unit and has_maker


def _normalize_header(value: Any) -> str:
    return _clean(value).replace(" ", "").replace("\n", "")

