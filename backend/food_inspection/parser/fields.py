"""不合格项解析与省市地名解析。"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

from config import DATA_ROOT
from food_inspection.parser.constants import (
    COLUMN_ALIASES,
    COMBINED_FAILURE_CELL,
    FAILURE_CELL_SEPS,
    FAILURE_HINT_CELL,
    SKIP_FAILURE_SCAN,
    UNIT_PATTERN,
)
from food_inspection.parser.classification import _parse_verdict_status
from food_inspection.parser.layout import (
    _extract_compact_combined_fields,
    _get_cell,
    _is_compact_combined_row,
)
from food_inspection.parser.text import _clean, is_inspection_agency, is_invalid_company



def _get_unqualified_cell_raw(cells: list[Any], col_map: dict[str, int]) -> str:
    """读取不合格项目列原文；「无」表示合格，不可经 _clean 抹掉。"""
    idx = col_map.get("unqualified_item")
    if idx is None or idx >= len(cells):
        return ""
    val = cells[idx]
    if val is None:
        return ""
    return str(val).strip()


def _is_absent_failure_marker(text: str) -> bool:
    """不合格项目列为「无」等表示该行合格。"""
    if not text:
        return True
    compact = re.sub(r"\s+", "", str(text).strip().replace("／", "/").replace("—", "-"))
    return compact.lower() in {
        "无",
        "暂无",
        "不详",
        "未知",
        "null",
        "none",
        "nan",
        "/",
        "-",
        "合格",
        "符合",
        "达标",
        "未检出",
        "nd",
    }


_SPECIFICATION_TEXT_RE = re.compile(
    r"(%?\s*vol|m[lI]/|ml/|/盒|/瓶|/袋|/包|计量称重|净含量|规格型号|散装)",
    re.IGNORECASE,
)


def _is_specification_text(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if _SPECIFICATION_TEXT_RE.search(raw):
        return True
    if re.fullmatch(r"[\d.%volI/LmMl盒瓶袋包/\s|｜丨，,+-]+", raw, re.IGNORECASE):
        return True
    return False


def _has_failure_sep(text: str) -> bool:
    text = text or ""
    if "||" in text or "║" in text or "‖" in text:
        return True
    if any(sep in text for sep in ("|", "｜", "丨")):
        return not _is_specification_text(text)
    return False


_DETECTION_VALUE_NARRATIVE_RE = re.compile(
    r"^(.+?)"
    r"(?:检测值|检出值|测定值)(?:为)?\s*"
    r"([^，,;；(（]+?)"
    r"(?:[，,;]?\s*[(（]?\s*标准值(?:为)?\s*"
    r"([^)）]+)"
    r"[)）]?)?\s*$"
)


def _split_detection_value_narrative(text: str) -> tuple[str, str, str]:
    """湖北等：二氧化硫残留量检测值为 0.117g/kg，(标准值为 0.05g/kg)。"""
    compact = _clean(text)
    if not compact:
        return "", "", ""
    match = _DETECTION_VALUE_NARRATIVE_RE.match(compact)
    if not match:
        return "", "", ""
    item = match.group(1).strip()
    measured = match.group(2).strip()
    standard = (match.group(3) or "").strip()
    if not item or not measured:
        return "", "", ""
    return item, measured, standard


def _split_combined_failure(text: str) -> tuple[str, str, str]:
    """拆分「项目║实测║标准」或「项目‖实测‖标准」合并单元格。"""
    raw = str(text or "").strip()
    if _is_absent_failure_marker(raw):
        return "", "", ""
    text = _clean(raw) or raw
    if not text:
        return "", "", ""
    if _is_specification_text(text):
        return "", "", ""

    for sep in FAILURE_CELL_SEPS:
        if sep not in text:
            continue
        if sep == "|" and _is_specification_text(text):
            continue
        parts = [p.strip() for p in text.split(sep) if p.strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return parts[0], parts[1], ""
        if len(parts) == 1:
            return parts[0], "", ""

    item, measured, standard = _split_detection_value_narrative(text)
    if item:
        return item, measured, standard
    return text, "", ""


def _extract_unit(text: str) -> str:
    match = UNIT_PATTERN.search(_clean(text))
    if not match:
        return ""
    unit = match.group(1)
    if unit.lower() == "mg/kg":
        return "mg/kg"
    if unit.lower() in ("μg/kg", "µg/kg"):
        return "μg/kg"
    return unit


def _normalize_decimal_text(text: str) -> str:
    """OCR 常把小数点重复，如 0..05 → 0.05。"""
    return re.sub(r"\.{2,}", ".", text)


def _parse_number(text: str) -> float | None:
    text = _clean(text)
    if not text or text in ("检出", "阳性", "+", "++"):
        return None
    match = re.search(r"([\d.]+)", text)
    if not match:
        return None
    try:
        return float(_normalize_decimal_text(match.group(1)))
    except ValueError:
        return None


def _parse_standard_limit(standard: str) -> tuple[str, float | None]:
    standard = _clean(standard)
    if not standard:
        return "unknown", None
    if "不得检出" in standard or standard in ("0", "0.0"):
        return "not_detected", 0.0

    for pattern, op in (
        (r"≤\s*([\d.]+)", "le"),
        (r"<\s*([\d.]+)", "lt"),
        (r"≥\s*([\d.]+)", "ge"),
        (r">\s*([\d.]+)", "gt"),
    ):
        match = re.search(pattern, standard)
        if match:
            try:
                return op, float(_normalize_decimal_text(match.group(1)))
            except ValueError:
                return op, _parse_number(match.group(1))

    number = _parse_number(standard)
    if number is not None:
        return "eq", number
    return "unknown", None


def _format_amount(value: str, unit: str) -> str:
    value = _clean(value)
    if not value:
        return "-"
    if unit and unit not in value:
        return f"{value} {unit}"
    return value


def _build_compliance_reason(item: str, unit: str, standard: str, measured: str) -> str:
    """根据标准值与实测值生成不合格说明。"""
    standard = _clean(standard)
    measured = _clean(measured)
    if not standard and not measured:
        return ""

    op, limit = _parse_standard_limit(standard)
    measured_num = _parse_number(measured)
    std_text = _format_amount(standard, unit)
    meas_text = _format_amount(measured, unit)

    if op == "not_detected":
        if measured in ("检出", "阳性", "+", "++") or (measured_num is not None and measured_num > 0):
            verdict = "检出，不合格"
        elif measured_num is None and measured:
            verdict = "不合格"
        else:
            verdict = "不合格"
        return f"标准: 不得检出；实测: {meas_text}（{verdict}）"

    if op in ("le", "lt") and limit is not None:
        if measured_num is not None:
            symbol = "≤" if op == "le" else "<"
            verdict = "超标，不合格" if measured_num > limit else "不合格"
            return f"标准: {symbol}{limit}{(' ' + unit) if unit else ''}；实测: {meas_text}（{verdict}）"
        return f"标准: {std_text}；实测: {meas_text}"

    if op in ("ge", "gt") and limit is not None:
        if measured_num is not None:
            symbol = "≥" if op == "ge" else ">"
            verdict = "不达标，不合格" if measured_num < limit else "不合格"
            return f"标准: {symbol}{limit}{(' ' + unit) if unit else ''}；实测: {meas_text}（{verdict}）"
        return f"标准: {std_text}；实测: {meas_text}"

    prefix = f"{item}：" if item else ""
    return f"{prefix}标准: {std_text or '-'}；实测: {meas_text or '-'}"


def _scan_row_for_combined_failure(cells: list[Any]) -> str:
    for cell in cells:
        text = _clean(cell)
        if COMBINED_FAILURE_CELL.search(text):
            return text
    return ""


def _cell_has_combined_failure(text: str) -> bool:
    text = _clean(text)
    return bool(text and COMBINED_FAILURE_CELL.search(text))


def _scan_row_for_failure_text(cells: list[Any], col_map: dict[str, int]) -> str:
    """扫描行内任意单元格，查找不合格项目说明（含列错位情况）。"""
    combined = _scan_row_for_combined_failure(cells)
    if combined:
        return combined

    skip_fields = {
        "company", "sampled_unit", "product", "address", "province_city",
        "inspection_result", "specification",
    }
    skip_indices = {col_map[f] for f in skip_fields if f in col_map}
    # 规格型号、生产日期等常见误匹配列：仅在有 ║/|| 分隔符时才视为不合格说明
    weak_fields = {"category"}
    weak_indices = {col_map[f] for f in weak_fields if f in col_map}

    spec_like = re.compile(
        r"(固形物|净含量|规格|计量称重|散装|生产日期|批号|g/袋|ml/|m[lI]/|L/|"
        r"%vol|/盒|/瓶|/袋|克\+|赠\d|×|包装)",
        re.IGNORECASE,
    )

    for idx, cell in enumerate(cells):
        text = _clean(cell)
        if not text or len(text) > 400:
            continue
        if idx in skip_indices:
            continue
        if _is_food_category(text):
            continue
        if SKIP_FAILURE_SCAN.match(text):
            continue
        if spec_like.search(text) and not _has_failure_sep(text):
            continue
        if _has_failure_sep(text):
            return text
        if idx in weak_indices:
            continue
        if FAILURE_HINT_CELL.search(text) and not re.fullmatch(r"[\d./\-]+", text):
            if any(k in text for k in ("不得检出", "不得使用", "超标", "检出值", "实测")):
                return text
    return ""


def _row_has_failure_info(cells: list[Any], col_map: dict[str, int]) -> bool:
    raw_item = _get_unqualified_cell_raw(cells, col_map)
    if raw_item:
        if _is_absent_failure_marker(raw_item):
            return False
        if _cell_has_combined_failure(raw_item) or _has_failure_sep(raw_item):
            return True
        if FAILURE_HINT_CELL.search(raw_item):
            return True
        item_part, measured, standard = _split_combined_failure(raw_item)
        if measured or standard:
            return True
        item = normalize_failure_item_name(item_part or raw_item)
        if item and not _is_junk_failure_item(item):
            return True
    if _scan_row_for_failure_text(cells, col_map):
        return True
    if _get_cell(cells, col_map, "measured_value") or _get_cell(cells, col_map, "standard_value"):
        return True
    remark = _get_cell(cells, col_map, "remark")
    if remark and any(k in remark for k in ("不合格", "超标", "检出", "不得检出", "不得使用")):
        return True
    return False


def _sheet_uses_verdict_column(col_map: dict[str, int], sheet_status: str) -> bool:
    return "inspection_result" in col_map or sheet_status == "result_column"


def _resolve_row_status(
    sheet_status: str,
    cells: list[Any],
    col_map: dict[str, int],
    file_mode: str,
) -> str:
    """合并公示表 / 检验结果列按行区分；有结论列时仅看结论，不看检验项目列。"""
    if sheet_status == "product_info_qualified":
        return "qualified"

    if file_mode == "qualified" and sheet_status == "qualified":
        return "qualified"

    if _sheet_uses_verdict_column(col_map, sheet_status):
        verdict = _get_cell(cells, col_map, "inspection_result")
        parsed = _parse_verdict_status(verdict)
        if parsed:
            return parsed
        cleaned = _clean(verdict)
        if cleaned in ("合格", "符合", "达标"):
            return "qualified"
        if cleaned.startswith("合格") and "不合格" not in cleaned:
            return "qualified"
        if cleaned.startswith("不合格") or cleaned.startswith("不符合"):
            return "unqualified"
        return "qualified"

    if file_mode == "combined" or sheet_status == "combined":
        return "unqualified" if _row_has_failure_info(cells, col_map) else "qualified"
    if sheet_status == "unqualified":
        if _row_has_failure_info(cells, col_map):
            return "unqualified"
        item = _get_cell(cells, col_map, "unqualified_item")
        return "unqualified" if item else "qualified"
    if _row_has_failure_info(cells, col_map):
        return "unqualified"
    return sheet_status or "qualified"


def _finalize_record_status(
    status: str,
    cells: list[Any],
    col_map: dict[str, int],
    sheet_status: str,
) -> str:
    """【新增兜底】将 result_column 等非标准状态归一为 qualified/unqualified。"""
    if status in ("qualified", "unqualified"):
        return status
    if status == "product_info_qualified":
        return "qualified"
    if _sheet_uses_verdict_column(col_map, sheet_status) or status == "result_column" or sheet_status == "result_column":
        verdict = _get_cell(cells, col_map, "inspection_result")
        parsed = _parse_verdict_status(verdict)
        if parsed:
            return parsed
        cleaned = _clean(verdict)
        if cleaned.startswith("不合格") or cleaned.startswith("不符合"):
            return "unqualified"
        return "qualified"
    return status or "qualified"


def _maybe_correct_compact_combined_row(
    cells: list[Any],
    company: str,
    sampled_unit: str,
    product: str,
    address: str,
    category: str,
) -> tuple[str, str, str, str, str, str] | None:
    """【新增兜底】合并公示表不合格段列左移时，仅在检测到错位后修正字段。"""
    if not _is_compact_combined_row(cells):
        return None
    fields = _extract_compact_combined_fields(cells)
    return (
        fields["company"],
        fields["sampled_unit"],
        fields["product"],
        fields.get("address") or address,
        fields.get("category") or category,
        fields["unqualified_raw"],
    )


def resolve_unqualified_fields(
    cells: list[Any],
    col_map: dict[str, int],
    remark: str = "",
) -> tuple[str, str]:
    """从不合格相关列提取项目名称与不合格说明。"""
    raw_item = _get_unqualified_cell_raw(cells, col_map)
    if _is_absent_failure_marker(raw_item):
        return "", ""
    raw_item = _clean(raw_item) or raw_item
    if not raw_item:
        raw_item = _scan_row_for_failure_text(cells, col_map)
    if not raw_item:
        category = _get_cell(cells, col_map, "category")
        if _cell_has_combined_failure(category):
            raw_item = category

    item_part, measured_combined, standard_combined = _split_combined_failure(raw_item)
    unit = _get_cell(cells, col_map, "item_unit")
    unqualified_idx = col_map.get("unqualified_item")
    measured_idx = col_map.get("measured_value")
    standard_idx = col_map.get("standard_value")
    standard = _get_cell(cells, col_map, "standard_value") or standard_combined
    measured = _get_cell(cells, col_map, "measured_value") or measured_combined
    if measured_idx is not None and measured_idx == unqualified_idx:
        measured = measured_combined
    if standard_idx is not None and standard_idx == unqualified_idx:
        standard = standard_combined

    if not unit:
        unit = _extract_unit(measured) or _extract_unit(standard)

    item = normalize_failure_item_name(item_part) or normalize_failure_item_name(raw_item)

    reason = ""
    if standard or measured:
        reason = _build_compliance_reason(item, unit, standard, measured)
    elif raw_item and not item_part and not measured_combined and not standard_combined:
        reason = _parse_unqualified_detail(raw_item)[1]

    if not reason and remark and "复检" not in remark:
        reason = remark
    if not reason and item:
        reason = f"不合格项目：{item}"
    return item, reason


def _parse_unqualified_detail(raw: str) -> tuple[str, str]:
    text = _clean(raw)
    if not text:
        return "", ""

    item, measured, standard = _split_detection_value_narrative(text)
    if item:
        normalized = normalize_failure_item_name(item) or item
        unit = _extract_unit(measured) or _extract_unit(standard)
        reason = _build_compliance_reason(normalized, unit, standard, measured)
        return normalized, reason

    for sep in FAILURE_CELL_SEPS:
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if len(parts) >= 3:
                return parts[0], f"检验结果: {parts[1]}；标准值: {parts[2]}"
            if len(parts) == 2:
                return parts[0], parts[1]
            if len(parts) == 1:
                return parts[0], ""

    return text, ""


PROVINCE_NAMES = (
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
)
PROVINCE_PATTERN = (
    r"(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门)"
    r"(?:壮族自治区|维吾尔自治区|回族自治区|自治区|省|市)?"
)
CITY_PATTERN = re.compile(r"([\u4e00-\u9fa5]{2,6}市)")

INVALID_CITY_KEYWORDS = (
    "超市", "百货", "商店", "饭店", "餐厅", "餐饮", "农贸", "集市", "市场",
    "有限公司", "经营部", "便利店", "商行", "生鲜", "购物中心", "门店",
    "食品", "商贸", "商场", "生活超市", "商城", "专营店", "批发", "零售",
)

FOOD_CATEGORY_KEYWORDS = (
    "食用农产品", "餐饮食品", "调味品", "水产制品", "酒类", "饮料",
    "冷冻饮品", "粮食加工品", "肉制品", "豆制品", "罐头", "糕点",
    "淀粉及淀粉制品", "炒货食品及坚果制品", "蔬菜制品", "水果制品",
    "保健食品", "特殊膳食", "婴幼儿配方", "餐饮具", "食品添加剂",
)


def _is_valid_city_name(name: str) -> bool:
    name = _clean(name)
    if not name or name == "未知城市":
        return False
    if any(kw in name for kw in INVALID_CITY_KEYWORDS):
        return False
    if not name.endswith(("市", "州", "盟")):
        return False
    if "县" in name or "镇" in name or "乡" in name or "村" in name or "超" in name:
        return False
    if len(name) > 6:
        return False

    city_key = name[:-1] if name.endswith("市") else name
    if city_key in CITY_PROVINCE_MAP:
        return True
    # 常见地级市/县级市：2~3 个汉字 + 市
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", city_key):
        return True
    return False


def _normalize_folder_city(name: str) -> str:
    """规范化文件夹中的城市名（如 咸宁市、汕头市）。"""
    name = _clean(name)
    if not name:
        return ""
    if re.fullmatch(r"\d{4}", name):
        return ""
    if len(name) > 12:
        return ""
    while name.endswith("市市"):
        name = name[:-1]
    if name.endswith(("市", "州", "盟")):
        return name
    return name


def _sanitize_city_name(name: str) -> str:
    name = _clean(name)
    if not name:
        return ""

    while name.endswith("市市"):
        name = name[:-1]

    for prefix in (
        "广西壮族自治区", "内蒙古自治区", "宁夏回族自治区",
        "新疆维吾尔自治区", "西藏自治区",
    ):
        if name.startswith(prefix):
            name = name[len(prefix):]

    for p in PROVINCE_NAMES:
        if name.startswith(p):
            rest = name[len(p):].lstrip("省")
            if rest:
                name = rest
            break

    if _is_valid_city_name(name):
        return name
    return ""


def _extract_valid_cities_from_text(text: str) -> list[str]:
    text = _clean(text)
    if not text:
        return []

    found: list[str] = []
    for key in sorted(CITY_PROVINCE_MAP, key=len, reverse=True):
        marker = key + "市"
        if marker in text and marker not in found:
            found.append(marker)

    for match in CITY_PATTERN.finditer(text):
        city = _sanitize_city_name(match.group(1))
        if city and city not in found:
            found.append(city)
    return found


def resolve_record_city(record: dict[str, Any]) -> str:
    """优先使用文件夹路径中的城市（与数据采集目录一致）。"""
    source_city = _normalize_folder_city(record.get("source_city") or "")
    if source_city:
        return source_city

    filepath = record.get("source_file") or ""
    if filepath:
        _, path_city = _extract_location_from_path(filepath)
        if path_city:
            return path_city
    return ""


FAILURE_ITEM_UNIT_SUFFIX = re.compile(
    r"[\(（][^)）]*(?:mg/kg|μg/kg|µg/kg|g/kg|mg/L|μg/L|CFU/g|CFU/mL|"
    r"/50cm²|cm²|g/100g|mg/100cm²|mL|L)[^)）]*[\)）]$",
    re.IGNORECASE,
)
FAILURE_ITEM_TRAILING_UNIT = re.compile(
    r"[,，]\s*(?:mg/kg|μg/kg|µg/kg|g/kg|mg/L|μg/L|CFU/g|CFU/mL|"
    r"/50cm²|cm²|g/100g|mg/100cm²).*$",
    re.IGNORECASE,
)
FAILURE_ITEM_JUNK_NAME = re.compile(
    r"^(kg|g|mg|ml|l|μg|µg|ug|%|cfu|koh|ph|mol|指数|合格率|以计|检出值|实测值|检出|出|不得检出|-+|—+)$",
    re.IGNORECASE,
)
FAILURE_ITEM_MEASUREMENT_ONLY = re.compile(
    r"^[\d./]+(?:\s*(?:μg|µg|ug|mg|g|kg|/|cm²|cm2|m²|%|CFU|KOH|pH))?$",
    re.IGNORECASE,
)
FAILURE_ITEM_AREA_ONLY = re.compile(r"^\d*cm²$", re.IGNORECASE)
FAILURE_ITEM_STANDARD_FRAGMENT = re.compile(
    r"^(标准|实测|限值)[:：]",
    re.IGNORECASE,
)
_STANDARD_LIMIT_TABLE_PREFIX = re.compile(
    r"^果[ⅠI1lⅡ2Ⅲ3Ⅳ4]*标准限值"
)

_HTML_TAG_FAILURE_ITEMS = frozenset(
    {
        "em",
        "span",
        "div",
        "br",
        "strong",
        "sub",
        "sup",
        "td",
        "tr",
        "th",
        "table",
        "html",
        "body",
        "head",
        "meta",
        "link",
        "style",
        "script",
        "img",
        "href",
        "nbsp",
        "quot",
        "amp",
        "lt",
        "gt",
    }
)

_ASCII_FAILURE_ITEM_ALLOW = frozenset({"pH", "Pb", "BPA", "COD"})


def _ascii_failure_item_allowed(text: str) -> bool:
    compact = _compact_failure_item_text(text)
    if not compact:
        return False
    if compact in _ASCII_FAILURE_ITEM_ALLOW:
        return True
    return compact.upper() in {name.upper() for name in _ASCII_FAILURE_ITEM_ALLOW}


_JUNK_FAILURE_ITEMS = frozenset(
    {
        "经抽样检验",
        "抽样检验",
        "检验结论为不合格",
        "检验结论为不合格。",
        "检验结果",
        "不合格",
        "不符合",
        "未标注",
        "检出",
        "出",
        "不得",
        "不得检出",
        "不得使用",
        "-",
        "—",
        "|",
        "以计",
        "小作",
        "小作坊",
        "实测",
        "标准",
        "限值",
        "一般不合格样品",
        "一般不合格报告",
        "一般不合格",
        "不合格样品",
        "合格样品",
        "结果",
        "结论",
        "盒",
        "vo",
        "vol",
        "备注",
        "说明",
        "不合格项",
        "不合格项目",
        "合格",
        "可接受",
        "不可接受",
        "接受",
        "满意",
        "符合",
        "通过",
        "未通过",
        "基本合格",
        "部分合格",
        "不合格品",
        "项目",
        "样品名称",
        "食品名称",
        "产品名称",
        "kg",
        "mg",
        "kg）",
        "mg）",
        "gkg",
        "gkg）",
        "计)，mg",
        "mgkg",
        "汤碗",
        "餐碗",
        "瓷碗",
        "密胺碗",
        "餐饮具",
        "消毒餐具",
        "食品接触用纸包装及容器等制品",
        "食品接触用纸",
        "纸包装及容器",
        "食品接触用",
        "包装及容器",
    }
)

_VERDICT_FAILURE_RE = re.compile(
    r"^(?:合格|不合格|符合|不符合|可接受|不可接受|接受|满意|通过|未通过|"
    r"基本合格|部分合格|不合格品|合格品|达标|不达标)$"
)

_META_FAILURE_ITEM_RE = re.compile(
    r"一般.*不合格|不合格样品|合格样品|监督抽检|抽检结论|检验结论|"
    r"^结果$|^结论$|^备注$|^说明$|不合格项?$|不合格报告|"
    r"不合格信息|抽检信息|样品信息"
)

# OCR 别名 / 缺字 → 标准不合格项目名
_FAILURE_ITEM_ALIASES: dict[str, str] = {
    "离子合成洗涤剂": "阴离子合成洗涤剂",
    "合成洗涤剂": "阴离子合成洗涤剂",
    "二氧化硫残 留量": "二氧化硫残留量",
    "二氧化硫残留 量": "二氧化硫残留量",
    "二氧化硫残 留 量": "二氧化硫残留量",
    "咪鲜胺和咪鲜胺锰盐项目": "咪鲜胺和咪鲜胺锰盐",
    "咪鲜胺和咪鲜胺锰盐I": "咪鲜胺和咪鲜胺锰盐",
    "咪鲜胺和咪鲜胺锰盐l": "咪鲜胺和咪鲜胺锰盐",
    "氯氰菊酯和高效氯氰菊酯": "氯氟氰菊酯和高效氯氟氰菊酯",
    "黄曲霉毒素Blg": "黄曲霉毒素B₁",
    "黄曲霉毒素Bl1180.2μg": "黄曲霉毒素B₁",
    "黄曲霉毒素B1": "黄曲霉毒素B₁",
    "黄曲霉毒素Bl": "黄曲霉毒素B₁",
    "黄曲霉毒素B": "黄曲霉毒素B₁",
    "酸价(KOH)": "酸价",
    "阴离子不合得成检洗出涤剂": "阴离子合成洗涤剂",
    "阴离子不合得成检出涤剂": "阴离子合成洗涤剂",
    "大肠菌群检出": "大肠菌群",
    "出大肠菌群": "大肠菌群",
    "大肠杆菌检出": "大肠菌群",
    "大肠杆菌": "大肠菌群",
    "大肠埃希氏菌": "大肠菌群",
    "大肠用菌群": "大肠菌群",
    "不得使用阴离子合成洗涤剂": "阴离子合成洗涤剂",
    "二氧化硫残量": "二氧化硫残留量",
    "二氧化滑溜残留量": "二氧化硫残留量",
    "二氧化硫残留": "二氧化硫残留量",
    "二氧化硫": "二氧化硫残留量",
    "计": "阴离子合成洗涤剂",
    "以计": "阴离子合成洗涤剂",
    "钠计": "阴离子合成洗涤剂",
    "苯磺酸钠计": "阴离子合成洗涤剂",
    "烷基苯磺酸钠计": "阴离子合成洗涤剂",
    "十二烷基苯磺酸钠计": "阴离子合成洗涤剂",
    "以十二烷基苯磺酸钠计": "阴离子合成洗涤剂",
    "氨基磺酸计": "阴离子合成洗涤剂",
    "磺酸钠计": "阴离子合成洗涤剂",
    "基磺酸计": "阴离子合成洗涤剂",
    "酸钠计": "阴离子合成洗涤剂",
    "孔雀石恩诺沙星": "恩诺沙星",
    "复检结果": "其他",
    "报告": "其他",
    "阴离子合成": "阴离子合成洗涤剂",
    "离子合成洗涤剂": "阴离子合成洗涤剂",
    "阴离子合成剂": "阴离子合成洗涤剂",
    "样品以Al计": "铝的残留量",
    "样品以AI计": "铝的残留量",
    "样品以铝计": "铝的残留量",
    "以Al计": "铝的残留量",
    "以Al计）": "铝的残留量",
    "以Al计)": "铝的残留量",
    "铝的残留量（干样品，以Al计）": "铝的残留量",
    "铝的残留量（干样品以Al计）": "铝的残留量",
    "铝的残留量（以即食海蜇中Al计）": "铝的残留量",
    "铝的残留量（以Al计）": "铝的残留量",
    "以AI计": "铝的残留量",
    "以铝计": "铝的残留量",
    "4-滴": "2,4-滴",
    "4-滴和2": "2,4-滴",
    "4-滴和 2": "2,4-滴",
    "4-滴和": "2,4-滴",
    "4-滴钠盐": "2,4-滴",
    "4-滴钠盐，mg": "2,4-滴",
    "2,4-滴和2": "2,4-滴",
    "2,4-滴和2,4-滴钠盐": "2,4-滴",
    "2,4-滴钠盐": "2,4-滴",
    "铅以Pb计": "铅",
    "以Cd计": "镉",
    "以山梨酸计": "山梨酸",
    "以脂肪计": "酸价",
    "氯苯氧乙酸钠": "4-氯苯氧乙酸钠",
}

_FAILURE_ITEM_CANONICAL_POOL: tuple[str, ...] | None = None
_FAILURE_ITEM_POOL_JUNK_MARKERS = (
    "销售",
    "抽检",
    "通告",
    "基本情况",
    "农药残留超标",
    "核查处置",
    "不合格食品",
    "均是",
    "均为",
    "都是",
)


def _failure_item_has_distortion(compact: str) -> bool:
    """叙述前缀/粘连单位等残片，不应作为标准项目名或合并目标。"""
    text = _compact_failure_item_text(compact)
    if not text:
        return False
    cleaned = _strip_failure_item_affixes(text)
    cleaned = _strip_failure_item_glued_unit_suffix(cleaned)
    return bool(cleaned and cleaned != text and len(cleaned) >= 2)


def _is_failure_item_pool_name(name: str) -> bool:
    compact = _compact_failure_item_text(name)
    if not compact or len(compact) > 36:
        return False
    if _is_junk_failure_item(compact):
        return False
    if _failure_item_has_distortion(compact):
        return False
    return not any(marker in compact for marker in _FAILURE_ITEM_POOL_JUNK_MARKERS)


def _failure_item_canonical_pool() -> tuple[str, ...]:
    """标准不合格项目名池（用于主干合并：短名/碎片并入完整名）。"""
    global _FAILURE_ITEM_CANONICAL_POOL
    if _FAILURE_ITEM_CANONICAL_POOL is not None:
        return _FAILURE_ITEM_CANONICAL_POOL
    pool = set(_FAILURE_ITEM_ALIASES.values()) | set(_FAILURE_ITEM_SYNONYM_TO_CANONICAL.values())
    try:
        import json
        from pathlib import Path

        from config import ROOT_DIR

        cache_dir = Path(ROOT_DIR) / "data" / "analytics_disk_cache"
        if cache_dir.is_dir():
            for path in sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for row in data.get("item_types") or []:
                    name = (row.get("name") or "").strip()
                    if name and name not in ("其他", "未标注") and _is_failure_item_pool_name(name):
                        pool.add(name)
                if pool:
                    break
    except Exception:
        pass
    _FAILURE_ITEM_CANONICAL_POOL = tuple(sorted(pool, key=len, reverse=True))
    return _FAILURE_ITEM_CANONICAL_POOL


def _merge_failure_item_stem(compact: str) -> str:
    """将缩写/碎片并入同一主干的标准项目名（如 阴离子合成 → 阴离子合成洗涤剂）。"""
    if not compact or compact in ("其他", "未标注"):
        return compact
    pool = _failure_item_canonical_pool()
    prefix_hits = [
        name
        for name in pool
        if _is_failure_item_pool_name(name)
        and name.startswith(compact)
        and len(name) > len(compact)
        and len(compact) >= 3
    ]
    if prefix_hits:
        return max(prefix_hits, key=len)
    suffix_hits = [
        name
        for name in pool
        if _is_failure_item_pool_name(name)
        and name.endswith(compact)
        and len(name) > len(compact)
        and len(compact) >= 2
    ]
    if suffix_hits:
        if len(suffix_hits) == 1:
            return suffix_hits[0]
        if compact == "洗涤剂":
            detergent = [name for name in suffix_hits if "阴离子" in name or "合成洗涤" in name]
            if detergent:
                return max(detergent, key=len)
        shared = suffix_hits[0][:2]
        grouped = [name for name in suffix_hits if name.startswith(shared)]
        if grouped:
            return max(grouped, key=len)
    if compact in pool:
        return compact
    return compact

# 「阴离子合成洗涤剂(以十二烷基苯磺酸钠计)」列错位/OCR 残片
_DETERGENT_MEASUREMENT_FRAGMENTS = frozenset({
    "计",
    "以计",
    "钠计",
    "苯磺酸钠计",
    "烷基苯磺酸钠计",
    "十二烷基苯磺酸钠计",
    "以十二烷基苯磺酸钠计",
    "氨基磺酸计",
    "磺酸钠计",
    "基磺酸计",
    "酸钠计",
})
_DETERGENT_MEASUREMENT_LEADING_RE = re.compile(
    r"^计[\d.]+(?:mg|μg|µg|ug|g)?(?:/100cm[²2]?)?",
    re.IGNORECASE,
)
_DETERGENT_MEASUREMENT_FRAGMENT_RE = re.compile(
    r"^(?:以)?(?:十?[二]?烷基)?苯?(?:磺)?(?:基)?(?:氨)?(?:基)?(?:磺)?酸?(?:钠)?计$"
)

# 「铝的残留量(以Al计)」列错位时整格只剩计量说明
_MEASUREMENT_BASIS_ELEMENT_MAP: dict[str, str] = {
    "铝": "铝的残留量",
    "al": "铝的残留量",
    "ai": "铝的残留量",
    "a1": "铝的残留量",
    "铅": "铅",
    "pb": "铅",
    "镉": "镉",
    "cd": "镉",
    "汞": "汞",
    "hg": "汞",
    "砷": "砷",
    "as": "砷",
    "脂肪": "酸价",
    "山梨酸": "山梨酸",
    "十二烷基苯磺酸钠": "阴离子合成洗涤剂",
    "苯磺酸钠": "阴离子合成洗涤剂",
    "磺酸钠": "阴离子合成洗涤剂",
}
_MEASUREMENT_BASIS_ONLY_RE = re.compile(r"^(?:样品)?以([A-Za-z\u4e00-\u9fa5]{1,16})计$")
_MEASUREMENT_BASIS_SUFFIX_RE = re.compile(r"^(.{1,24}?)以([A-Za-z\u4e00-\u9fa5]{1,16})计$")

# 去掉「检出 / 不得使用」等前后缀后再映射到标准名
_FAILURE_ITEM_AFFIX_PREFIXES = (
    "不得使用",
    "不得检出",
    "检出",
    "出",
    "其中",
    "用",
    "抽检项目中",
    "残留量",
    "均是",
    "均为",
    "都是",
)
_FAILURE_ITEM_GLUED_UNIT_SUFFIX = re.compile(
    r"(?:μg/kg|mg/kg|g/100g|mg/100cm²|/50cm²|μg|µg|ug|mg|g/kg|kg|g|ml|l|cfu)$",
    re.IGNORECASE,
)
_FAILURE_ITEM_AFFIX_SUFFIXES = ("检出", "不得使用", "不得检出", "I检出", "丨检出")
_FAILURE_ITEM_SYNONYM_TO_CANONICAL = {
    "大肠杆菌": "大肠菌群",
    "大肠埃希氏菌": "大肠菌群",
    "合成洗涤剂": "阴离子合成洗涤剂",
    "离子合成洗涤剂": "阴离子合成洗涤剂",
    "阴离子合成剂": "阴离子合成洗涤剂",
    "二氧化硫": "二氧化硫残留量",
    "二氧化硫残留": "二氧化硫残留量",
    "二氧化硫残量": "二氧化硫残留量",
    "二氧化硫浸出量": "二氧化硫残留量",
}

_FAILURE_ITEM_OCR_FIXES = (
    ("二氧化滑溜", "二氧化硫"),
)

_FAILURE_ITEM_MEASUREMENT = re.compile(
    r"^[\d.]+(?:\s*(?:μg|µg|ug|mg|g|kg|/|cm²|cm2|m²|%|CFU|KOH|pH))+$",
    re.IGNORECASE,
)
_FAILURE_ITEM_LIMIT_ONLY = re.compile(
    r"^[≤≥<>][\d./]+(?:\s*(?:μg|µg|ug|mg|g|kg|%))?$",
    re.IGNORECASE,
)
_FAILURE_ITEM_PAREN_NUMBER = re.compile(r"^\)[\d./]+")
_FAILURE_ITEM_CHINESE = re.compile(
    r"[\u4e00-\u9fa5][\u4e00-\u9fa5₀₁₂₃₄₅₆₇₈₉A-Za-z0-9\[\]a]{1,28}"
)
_COLIFORM_ITEM_RE = re.compile(r"大肠(?:杆菌|菌群|埃希氏菌)")
_CHEMICAL_ITEM_PREFIX_RE = re.compile(r"^[\d]+(?:[,.][\d]+)?-")


def _resolve_coliform_item_name(text: str) -> str:
    """OCR/表头残片中含大肠菌群相关字样时，统一归并为「大肠菌群」。"""
    compact = _compact_failure_item_text(text)
    if compact and _COLIFORM_ITEM_RE.search(compact):
        return "大肠菌群"
    return ""


def _trim_failure_item_leading_junk(text: str) -> str:
    """去掉行号/数值前缀，保留 4-氯苯氧乙酸钠 等化学品编号前缀。"""
    compact = _compact_failure_item_text(text)
    if not compact:
        return ""
    if _CHEMICAL_ITEM_PREFIX_RE.match(compact):
        return compact
    match = re.search(r"[\u4e00-\u9fa5]", compact)
    if match:
        return compact[match.start() :]
    return compact


def _compact_failure_item_text(text: str) -> str:
    """去掉 OCR 在汉字间插入的空格，便于合并同一项目。"""
    return re.sub(r"\s+", "", text).strip()


def _apply_failure_item_alias(text: str) -> str:
    if text in _FAILURE_ITEM_ALIASES:
        return _FAILURE_ITEM_ALIASES[text]
    compact = _compact_failure_item_text(text)
    if compact in _FAILURE_ITEM_ALIASES:
        return _FAILURE_ITEM_ALIASES[compact]
    if re.match(r"^计[\d.]", compact) and re.search(
        r"(?:洗剂|涤剂|洗涤剂|磺酸|苯磺酸)", compact
    ):
        return "阴离子合成洗涤剂"
    if re.search(r"^(?:洗剂|涤剂)", compact) and re.search(
        r"(?:磺酸|烷基|苯磺酸|洗涤剂)", compact
    ):
        return "阴离子合成洗涤剂"
    if re.search(r"阴离子.{0,6}洗涤剂", compact):
        return "阴离子合成洗涤剂"
    if re.search(r"阴离子.{0,8}(?:洗|涤)", compact):
        return "阴离子合成洗涤剂"
    if "阴离子" in compact and "洗涤剂" in compact:
        return "阴离子合成洗涤剂"
    if re.search(r"孔雀石绿", compact):
        return "其他"
    if "恩诺沙星" in compact and re.search(r"孔雀石", compact):
        return "恩诺沙星"
    if compact in ("复检结果", "报告") or compact.endswith("报告"):
        return "其他"
    if "防腐剂混合使用" in compact:
        return "防腐剂"
    normalized = re.sub(r"黄曲霉毒素B[lL1]", "黄曲霉毒素B₁", compact)
    normalized = re.sub(r"黄曲霉毒素Blg", "黄曲霉毒素B₁", normalized)
    if normalized.startswith("黄曲霉毒素B") and normalized != "黄曲霉毒素B₁":
        normalized = "黄曲霉毒素B₁"
    return normalized


def _strip_failure_item_measurement_narrative(text: str) -> str:
    """去掉「项目实测值分别为」等检测说明尾巴，保留真实项目名。"""
    compact = _compact_failure_item_text(text)
    if not compact:
        return ""
    for marker in (
        "项目实测值分别为",
        "项目实测值",
        "检验项目实测",
        "项目实测",
        "项目检出",
        "项目不符合",
    ):
        if marker in compact:
            head = compact.split(marker, 1)[0]
            if len(head) >= 2:
                return head
    stripped = re.sub(r"(?:检验)?项目(?:实测|检出)(?:值)?(?:分别为|为|超标)?.*$", "", compact).strip()
    return stripped or compact


def _strip_failure_item_punctuation(text: str) -> str:
    compact = text
    edge_junk = re.compile(
        r"^[^\u4e00-\u9fa5A-Za-z0-9₀₁₂₃₄₅₆₇₈₉]+|"
        r"[^\u4e00-\u9fa5A-Za-z0-9₀₁₂₃₄₅₆₇₈₉]+$"
    )
    for _ in range(4):
        prev = compact
        compact = edge_junk.sub("", compact)
        if compact == prev:
            break
    return compact.strip()


def _apply_failure_item_ocr_fixes(text: str) -> str:
    compact = text
    for src, dst in _FAILURE_ITEM_OCR_FIXES:
        compact = compact.replace(src, dst)
    return compact


def _strip_failure_item_affixes(text: str) -> str:
    compact = _compact_failure_item_text(text)
    for _ in range(4):
        prev = compact
        for prefix in _FAILURE_ITEM_AFFIX_PREFIXES:
            if compact.startswith(prefix) and len(compact) > len(prefix) + 1:
                compact = compact[len(prefix) :]
        for suffix in _FAILURE_ITEM_AFFIX_SUFFIXES:
            if compact.endswith(suffix) and len(compact) > len(suffix) + 1:
                compact = compact[: -len(suffix)]
        if compact == prev:
            break
    return compact


def _strip_failure_item_glued_unit_suffix(text: str) -> str:
    """去掉粘连在项目名末尾的单位残片，如 吡唑醚菌酯mg。"""
    compact = _compact_failure_item_text(text)
    if not compact or not re.search(r"[\u4e00-\u9fa5]", compact):
        return compact
    for _ in range(3):
        prev = compact
        compact = _FAILURE_ITEM_GLUED_UNIT_SUFFIX.sub("", compact)
        if compact == prev:
            break
    return compact


def _map_measurement_basis(basis: str) -> str:
    """「以Al计」「以山梨酸计」等计量基准 → 对应检测项目。"""
    key = _compact_failure_item_text(basis)
    if not key:
        return ""
    if key in _MEASUREMENT_BASIS_ELEMENT_MAP:
        return _MEASUREMENT_BASIS_ELEMENT_MAP[key]
    low = key.lower()
    if low in _MEASUREMENT_BASIS_ELEMENT_MAP:
        return _MEASUREMENT_BASIS_ELEMENT_MAP[low]
    stem = _merge_failure_item_stem(key)
    if stem != key:
        return stem
    if key in _failure_item_canonical_pool():
        return key
    return ""


def _resolve_measurement_basis_fragment(text: str) -> str:
    """「样品以Al计」「铅以Pb计」等计量说明残片 → 真实不合格项目。"""
    compact = _compact_failure_item_text(text)
    if not compact:
        return ""
    only = _MEASUREMENT_BASIS_ONLY_RE.fullmatch(compact)
    if only:
        mapped = _map_measurement_basis(only.group(1))
        return mapped or compact
    suffix = _MEASUREMENT_BASIS_SUFFIX_RE.fullmatch(compact)
    if suffix:
        item_part, basis = suffix.group(1), suffix.group(2)
        mapped_basis = _map_measurement_basis(basis)
        item_compact = _compact_failure_item_text(item_part)
        if item_compact and item_compact in _MEASUREMENT_BASIS_ELEMENT_MAP.values():
            return item_compact
        if item_compact and len(item_compact) >= 2:
            item_norm = _apply_failure_item_alias(item_compact)
            if item_norm in _failure_item_canonical_pool() or item_norm in _MEASUREMENT_BASIS_ELEMENT_MAP.values():
                return item_norm
            if mapped_basis and (item_compact == mapped_basis or item_compact in mapped_basis):
                return mapped_basis
            if mapped_basis and item_compact in ("铅", "镉", "汞", "砷", "铝"):
                return mapped_basis
        if mapped_basis:
            return mapped_basis
    return compact


def _resolve_detergent_measurement_fragment(text: str) -> str:
    """「以十二烷基苯磺酸钠计」等计量后缀残片 → 阴离子合成洗涤剂。"""
    compact = _compact_failure_item_text(text)
    if not compact:
        return ""
    if compact in _DETERGENT_MEASUREMENT_FRAGMENTS:
        return "阴离子合成洗涤剂"
    if _DETERGENT_MEASUREMENT_FRAGMENT_RE.fullmatch(compact):
        return "阴离子合成洗涤剂"
    return compact


def _strip_trailing_ocr_letter(text: str) -> str:
    """OCR 常在中文项目名末尾多出 I/l/1（如「咪鲜胺锰盐I」）。"""
    compact = _compact_failure_item_text(text)
    if len(compact) >= 3 and compact[-1] in "Il1" and re.match(r"[\u4e00-\u9fa5]", compact[-2]):
        return compact[:-1]
    return compact


def _canonical_failure_item_name(text: str) -> str:
    """合并「大肠菌群/大肠杆菌/…检出」等同义写法。"""
    compact = _compact_failure_item_text(text)
    compact = _strip_failure_item_punctuation(compact)
    if not compact:
        return ""
    compact = _strip_trailing_ocr_letter(compact)
    compact = _resolve_detergent_measurement_fragment(compact)
    compact = _resolve_measurement_basis_fragment(compact)
    compact = _apply_failure_item_ocr_fixes(compact)
    if compact in _FAILURE_ITEM_SYNONYM_TO_CANONICAL:
        return _FAILURE_ITEM_SYNONYM_TO_CANONICAL[compact]
    compact = _strip_failure_item_affixes(compact)
    compact = _strip_failure_item_glued_unit_suffix(compact)
    compact = _strip_failure_item_punctuation(compact)
    compact = _apply_failure_item_ocr_fixes(compact)
    compact = _apply_failure_item_alias(compact)
    if compact in _FAILURE_ITEM_SYNONYM_TO_CANONICAL:
        return _FAILURE_ITEM_SYNONYM_TO_CANONICAL[compact]
    if compact.startswith("二氧化硫") and len(compact) <= 10:
        tail = compact[len("二氧化硫") :]
        if tail in ("", "残留", "残量", "残留量", "浸出量"):
            return "二氧化硫残留量"
    coliform = _resolve_coliform_item_name(compact)
    if coliform:
        return coliform
    compact = _FAILURE_ITEM_SYNONYM_TO_CANONICAL.get(compact, compact)
    compact = _merge_failure_item_stem(compact)
    if _MEASUREMENT_BASIS_ONLY_RE.fullmatch(compact):
        return ""
    return compact


def _split_multi_items(text: str) -> list[str]:
    """拆分同一单元格内的多项不合格项目（不把 g/100g 等单位里的 / 当分隔符）。"""
    text = _clean(text)
    if not text:
        return []
    parts = re.split(r"[、;；|｜丨]+", text)
    if len(parts) == 1 and "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
    return [part.strip() for part in parts if part.strip()]


def _recover_items_from_garbled_text(raw: str) -> list[str]:
    """从 OCR 粘连字段里捞取中文项目名。"""
    text = _clean(raw)
    if not text:
        return []
    found: list[str] = []
    for match in _FAILURE_ITEM_CHINESE.finditer(text):
        candidate = _apply_failure_item_alias(normalize_failure_item_name(match.group(0)))
        if candidate and candidate not in found and not _is_junk_failure_item(candidate):
            found.append(candidate)
    return found


def _leading_item_from_reason(text: str) -> str:
    """reason 常见格式：项目；项目：标准… 或 项目；标准…"""
    text = _clean(text)
    if not text:
        return ""

    match = re.match(r"^([^；;|║\n]+?)[；;]", text)
    if match:
        head = _apply_failure_item_alias(normalize_failure_item_name(match.group(1)))
        if head:
            return head

    match = re.search(r"实测[:：]\s*([^（(\|║‖\n]+)", text)
    if match:
        head = _apply_failure_item_alias(normalize_failure_item_name(match.group(1)))
        if head:
            return head

    return ""

_JUNK_FAILURE_PREFIXES = (
    "标准:",
    "标准：",
    "实测:",
    "实测：",
    "限值:",
    "限值：",
    "经抽样检验",
    "检验结论",
    "监督抽检",
    "该产品经",
    "经检验",
    "的食品",
    "不合格项目：标准",
    "不合格项目:标准",
)


_ORG_FAILURE_ITEM_MARKERS = (
    "科学院",
    "研究所",
    "研究院",
    "检验所",
    "质量监督",
    "食品检验",
    "有限公司",
    "通量检",
    "生物与医学工程",
    "医学工程研",
    "生态环境与",
    "生态环境与土壤",
    "生态环境与医学",
    "检验检测认证",
    "华测检测",
    "谱尼测试",
    "广电计量",
    "认证集团",
)
_ORG_FAILURE_ITEM_FRAGMENTS = (
    "物与医学工程",
    "究所广东省",
    "研究所有限",
    "测科技有限公司",
    "通量检",
    "检业研究",
    "食品工业",
    "质量防督",
    "检司",
    "海关技术",
    "广州海关",
    "广州海",
    "拱北海关",
    "华测检测",
    "谱尼测试",
    "广电计量",
    "检验检测认证",
    "心广州海关",
    "中心拱北海关",
    "团股份有限",
    "谱尼测试集团",
)

_ORG_FAILURE_ITEM_SPLIT_RE = re.compile(r"[、,，;；|｜丨/]+")


def _is_single_org_failure_item_name(compact: str) -> bool:
    if not compact:
        return False
    if any(marker in compact for marker in _ORG_FAILURE_ITEM_FRAGMENTS):
        return True
    if len(compact) < 4:
        return False
    if is_inspection_agency(compact):
        return True
    if compact.endswith("检司") or compact.startswith("测科技"):
        return True
    if "技术中心" in compact and re.search(
        r"(海关|检测|检验|测试|认证|检疫|质检)", compact
    ):
        return True
    if "海关" in compact and len(compact) >= 6:
        return True
    if any(marker in compact for marker in _ORG_FAILURE_ITEM_MARKERS):
        if len(compact) >= 8 or "公司" in compact or "集团" in compact:
            return True
    if is_invalid_company(compact) and len(compact) > 8 and (
        "公司" in compact or "集团" in compact or "中心" in compact
    ):
        return True
    return False


def _is_org_failure_item_name(text: str) -> bool:
    """列错位/OCR 把抽样检测机构名写入不合格项目字段。"""
    compact = re.sub(r"\s+", "", _clean(text))
    if not compact:
        return False
    parts = [p.strip() for p in _ORG_FAILURE_ITEM_SPLIT_RE.split(compact) if p.strip()]
    if len(parts) > 1:
        return all(_is_single_org_failure_item_name(p) for p in parts)
    return _is_single_org_failure_item_name(compact)


def _is_junk_failure_item(text: str) -> bool:
    name = _clean(text)
    if not name:
        return True
    compact = re.sub(r"\s+", "", name)
    if compact.lower() in _HTML_TAG_FAILURE_ITEMS:
        return True
    if compact in _JUNK_FAILURE_ITEMS:
        return True
    if not re.search(r"[\u4e00-\u9fa5]", compact):
        if _ascii_failure_item_allowed(compact):
            return False
        return True
    if _META_FAILURE_ITEM_RE.search(compact):
        return True
    if _VERDICT_FAILURE_RE.fullmatch(compact):
        return True
    if any(name.startswith(prefix) for prefix in _JUNK_FAILURE_PREFIXES):
        return True
    if FAILURE_ITEM_STANDARD_FRAGMENT.match(name):
        return True
    if FAILURE_ITEM_MEASUREMENT_ONLY.fullmatch(name):
        return True
    if _FAILURE_ITEM_MEASUREMENT.fullmatch(name):
        return True
    if _FAILURE_ITEM_LIMIT_ONLY.fullmatch(name):
        return True
    if _FAILURE_ITEM_PAREN_NUMBER.match(name):
        return True
    if re.fullmatch(r"[≤≥<>]+", name):
        return True
    if re.fullmatch(r"[A-Za-z]", name):
        return True
    if re.fullmatch(r"[\d./\s]+", name):
        return True
    if not re.search(r"[\u4e00-\u9fa5]", name) and re.search(r"\d", name):
        return True
    if FAILURE_ITEM_AREA_ONLY.fullmatch(name):
        return True
    if FAILURE_ITEM_JUNK_NAME.match(name):
        return True
    if UNIT_PATTERN.fullmatch(name):
        return True
    if re.fullmatch(r"[\d.]+", name):
        return True
    if name.startswith("|") or "|不得" in name or "丨不得" in name or (
        "不得检出" in name and len(name) <= 8
    ):
        return True
    if re.fullmatch(r"[\d./\s]+(?:μg|µg|ug|mg|kg|g|cm²|cm2|%)+", name, re.I):
        return True
    if re.search(r"\d+\s*cm[²2]", name, re.I) or re.search(r"/\s*\d+\s*cm", name, re.I):
        return True
    if any(dish in name for dish in ("菜盘", "餐盘", "瓷盘", "深碟", "骨碟", "圆形盘", "方形盘")):
        return True
    if re.search(r"[:：]\s*标准", name):
        return True
    if any(marker in name for marker in ("标准值", "检出！", "不得检出，", "■", "结果■")):
        return True
    if len(name) > 40:
        return True
    if _is_org_failure_item_name(name):
        return True
    if _is_specification_text(name):
        return True
    if re.fullmatch(r"盒[，,]?[\d.]+%?\s*vol", compact, re.IGNORECASE):
        return True
    return False


def _strip_failure_item_noise(text: str) -> str:
    text = _clean(text)
    if not text:
        return ""

    text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*)?/?>", "", text)
    text = re.sub(r"&(?:nbsp|lt|gt|amp|quot|#?\d+);", " ", text, flags=re.I)

    text = re.sub(r"[.。…]+$", "", text).strip()
    text = re.sub(r"\.{2,}$", "", text).strip()

    match = re.match(r"^([^：:]+)[：:]\s*标准", text)
    if match:
        text = match.group(1).strip()

    if not _CHEMICAL_ITEM_PREFIX_RE.match(_compact_failure_item_text(text)):
        for _ in range(5):
            stripped = re.sub(r"^[\d./\s]+", "", text, count=1).strip()
            stripped = re.sub(
                r"^(?:μg|µg|ug|mg|g/kg|/kg|kg|mg|g|ml|l|%|cm²|cm2|m²)",
                "",
                stripped,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
            compact = _compact_failure_item_text(stripped)
            if _DETERGENT_MEASUREMENT_LEADING_RE.match(compact):
                rest = _DETERGENT_MEASUREMENT_LEADING_RE.sub("", compact, count=1).strip()
                if rest and re.search(r"(?:洗剂|涤剂|洗涤剂|磺酸)", rest):
                    stripped = rest
                else:
                    return "阴离子合成洗涤剂"
            if stripped == text:
                break
            text = stripped

    match = re.search(r"[\u4e00-\u9fa5]", text)
    if match:
        text = _trim_failure_item_leading_junk(text)
    elif not _ascii_failure_item_allowed(text):
        return ""

    if text.endswith("项目") and len(text) > 4:
        text = text[:-2].strip()

    if re.search(r"[：:]", text):
        head = re.split(r"[：:]", text, maxsplit=1)[0].strip()
        if head and not head.startswith(("标准", "实测", "限值")):
            text = head

    return text.strip()


def _strip_standard_limit_prefix(text: str) -> str:
    """去掉「果Ⅱ标准限值」等表头前缀，保留真实不合格项目名。"""
    compact = _compact_failure_item_text(text)
    if not compact:
        return text
    match = _STANDARD_LIMIT_TABLE_PREFIX.match(compact)
    if match:
        rest = compact[match.end() :].strip()
        return rest or text
    if compact.startswith("标准限值") and len(compact) > 4:
        return compact[4:].strip() or text
    return text


def _extract_failure_items_from_reason(raw: str) -> list[str]:
    """从 reason/remark 文本提取不合格项目名称，避免把「标准/实测」片段当项目。"""
    text = _clean(raw)
    if not text:
        return []

    leading = _leading_item_from_reason(text)
    if leading:
        return [leading]

    if _is_junk_failure_item(text) and "实测" not in text and "标准" not in text:
        return []

    for prefix in ("不合格项目：", "不合格项目:", "不合格项目"):
        if text.startswith(prefix):
            head = normalize_failure_item_name(text[len(prefix) :])
            return [head] if head else []

    match = re.match(r"^([^：:；;|║\n]+)[：:]\s*标准", text)
    if match:
        head = normalize_failure_item_name(match.group(1))
        if head:
            return [head]

    found: list[str] = []
    for segment in re.split(r"[；;]+", text):
        segment = segment.strip()
        if not segment or _is_junk_failure_item(segment):
            continue
        if segment.startswith(("标准", "实测", "限值")):
            measured = re.search(r"实测[:：]\s*([^；;|║]+)", segment)
            if measured:
                segment = measured.group(1).strip()
            else:
                continue
        for sep in FAILURE_CELL_SEPS:
            if sep in segment:
                segment = segment.split(sep)[0].strip()
                break
        name = normalize_failure_item_name(segment)
        if name and name not in found:
            found.append(name)

    if found:
        return found

    for measured in re.finditer(r"实测[:：]\s*([^；;|║\n]+)", text):
        segment = measured.group(1).strip()
        for sep in FAILURE_CELL_SEPS:
            if sep in segment:
                segment = segment.split(sep)[0].strip()
                break
        name = normalize_failure_item_name(segment)
        if name and name not in found:
            found.append(name)

    if found:
        return found

    for sep in FAILURE_CELL_SEPS:
        if sep in text:
            head = normalize_failure_item_name(text.split(sep)[0])
            return [head] if head else []

    head = normalize_failure_item_name(text)
    return [head] if head else []


def normalize_failure_item_name(raw: str) -> str:
    text = _strip_failure_item_noise(raw)
    text = _strip_standard_limit_prefix(text)
    text = _strip_failure_item_measurement_narrative(text)
    if not text:
        return ""

    coliform = _resolve_coliform_item_name(text) or _resolve_coliform_item_name(raw)
    if coliform:
        return coliform

    for sep in FAILURE_CELL_SEPS:
        if sep in text:
            first = text.split(sep)[0].strip()
            if first:
                nested = normalize_failure_item_name(first)
                if nested:
                    return nested
            break

    narrative_item, _, _ = _split_detection_value_narrative(text)
    if narrative_item:
        text = narrative_item

    if _is_junk_failure_item(text):
        return ""

    for prefix in ("不合格项目：", "不合格项目:", "不合格项目", "不合格：", "不合格:", "不符合：", "不符合:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()

    head_match = re.match(
        r"^((?:[\d]+(?:[,.][\d]+)?-)?[\u4e00-\u9fa5A-Za-z\[\]a]+(?:和[\u4e00-\u9fa5A-Za-z\[\]a]+)?)",
        _compact_failure_item_text(text),
    )
    if head_match and len(head_match.group(1)) >= 2:
        text = head_match.group(1)

    match = re.match(
        r"^([\u4e00-\u9fa5A-Za-z（）()·\-0-9.%]+?)"
        r"(?:检测值|检出值|测定值|检测值为|检出值为)",
        text,
    )
    if match:
        text = match.group(1).strip()

    text = FAILURE_ITEM_UNIT_SUFFIX.sub("", text).strip()
    text = FAILURE_ITEM_TRAILING_UNIT.sub("", text).strip()
    text = re.sub(r"[,，]\s*/50cm².*$", "", text).strip()
    text = text.replace("（", "(").replace("）", ")")
    # 铅(Pb)、酸价(KOH) 等去掉括号说明
    text = re.sub(r"\([^)]{0,24}\)$", "", text).strip()
    text = text.split("(")[0].split("（")[0].strip()

    if any(marker in text for marker in ("标准值", "检出！", "不得检出，", "■", "结果■")):
        recovered = re.findall(
            r"[\u4e00-\u9fa5][\u4e00-\u9fa5₀₁₂₃₄₅₆₇₈₉A-Za-z0-9]{1,20}",
            _clean(raw),
        )
        text = ""
        for candidate in sorted(recovered, key=len, reverse=True):
            candidate = candidate.split("(")[0].split("（")[0].strip()
            if len(candidate) >= 2 and not _is_junk_failure_item(candidate):
                text = candidate
                break
        if not text:
            return ""

    if FAILURE_ITEM_JUNK_NAME.match(text) and not _ascii_failure_item_allowed(text):
        return ""
    if FAILURE_ITEM_MEASUREMENT_ONLY.fullmatch(text):
        return ""
    if FAILURE_ITEM_AREA_ONLY.fullmatch(text):
        return ""
    if UNIT_PATTERN.fullmatch(text):
        return ""
    if _is_junk_failure_item(text):
        return ""

    if any(text == cat or text.startswith(cat) for cat in FOOD_CATEGORY_KEYWORDS):
        return ""

    text = _compact_failure_item_text(text)
    if not text or _is_junk_failure_item(text):
        return ""
    text = _strip_failure_item_measurement_narrative(text)
    text = re.sub(r"项目(?:实测|检出|不符合).*$", "", text).strip()
    text = _apply_failure_item_alias(text)
    return _canonical_failure_item_name(text)


_FOOD_PRODUCT_HINTS = (
    "馒头", "白酒", "啤酒", "米线", "米粉", "香蕉", "苹果", "葡萄", "龙眼",
    "干杂", "干笋", "粉条", "泥鳅", "白芷", "桂皮", "豆皮", "豆干", "山药",
    "餐盘", "餐碗", "筷子", "碗", "盘", "杯", "勺", "自制", "散装", "瓜子",
    "荔枝", "韭菜", "姜", "鱼", "虾", "肉", "菜", "果", "面", "油", "酱",
    "香辛料", "调味品", "蛋糕", "饮用水", "包装", "甘薯", "餐饮具", "蘸料",
)

_INSPECTION_ITEM_EXACT = frozenset(
    name
    for name in (
        set(_FAILURE_ITEM_ALIASES.values())
        | {
            "大肠菌群",
            "菌落总数",
            "铜绿假单胞菌",
            "金黄色葡萄球菌",
            "沙门氏菌",
            "志贺氏菌",
            "副溶血性弧菌",
            "霉菌",
            "酵母",
            "阴离子合成洗涤剂",
            "甜蜜素",
            "二氧化硫残留量",
            "恩诺沙星",
            "多西环素",
            "噻虫胺",
            "毒死蜱",
            "铅",
            "镉",
            "汞",
            "砷",
        }
    )
    if name
)


_INVALID_PRODUCT_PATTERNS = (
    re.compile(r"残留量"),
    re.compile(r"不得检出|不得使用"),
    re.compile(r"项目不符合"),
    re.compile(r"║|\d+g/kg", re.I),
    re.compile(r"^其(钠|钾)盐$"),
    re.compile(r"^100cm"),
    re.compile(r"^kg║"),
)


def _looks_like_failure_item_fragment(text: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(text))
    if not compact:
        return False
    if any(p.search(compact) for p in _INVALID_PRODUCT_PATTERNS):
        return True
    if re.search(r"及其(钠|钾)盐", compact):
        return True
    if re.search(r"以[\u4e00-\u9fffA-Za-z]+计", compact):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{1,8}", compact):
        if normalize_failure_item_name(compact) in _INSPECTION_ITEM_EXACT:
            return True
    return False


def recover_product_from_misplaced_failure_item(name: str) -> str:
    """产品字段误填不合格项目时，尝试从「产品…，大肠菌群」类串中拆回产品名。"""
    from food_inspection.parser.text import normalize_product_name

    text = re.sub(r"\s+", "", _clean(name))
    if not text or looks_like_inspection_item_not_product(text):
        return ""
    for sep in ("），", "）,", "，", ","):
        if sep not in text:
            continue
        prefix = text.split(sep, 1)[0].strip("，, ")
        suffix = text.split(sep, 1)[1].strip("，, ")
        if prefix and suffix and looks_like_inspection_item_not_product(suffix):
            if not looks_like_inspection_item_not_product(prefix):
                return normalize_product_name(prefix)
    return ""


def looks_like_inspection_item_not_product(name: str) -> bool:
    """检测项目名（如大肠菌群、甜蜜素）不应作为产品名统计。"""
    text = re.sub(r"\s+", "", _clean(name))
    if not text or len(text) > 80:
        return False
    if _looks_like_failure_item_fragment(text):
        return True
    if any(h in text for h in _FOOD_PRODUCT_HINTS):
        return False
    normalized = normalize_failure_item_name(text)
    if not normalized:
        return False
    if normalized in _INSPECTION_ITEM_EXACT or text in _INSPECTION_ITEM_EXACT:
        return True
    if text in _FAILURE_ITEM_ALIASES or normalized in set(_FAILURE_ITEM_ALIASES.values()):
        return True
    if normalized == _canonical_failure_item_name(text) and len(text) <= 32:
        if re.search(
            r"(及其钠盐|及其钾盐|胺|唑|灵|霉素|菌群|单胞菌|致病菌|霉菌|酵母|甜蜜素|二氧化硫|"
            r"铅|镉|汞|砷|洗涤剂|色素|防腐剂|抗生素|沙门|葡萄球菌|吡虫|噻虫|氯氟|恩诺|"
            r"柠檬黄|山梨酸|脱氢乙酸|苯醚|咪鲜胺|氧乐果|克百威|水胺|腈苯|菌落总数|铝的)",
            text,
        ):
            return True
    parts = re.split(r"[、,，;；/]+", text)
    if len(parts) > 1 and all(
        normalize_failure_item_name(part.strip()) in _INSPECTION_ITEM_EXACT
        or looks_like_inspection_item_not_product(part.strip())
        for part in parts
        if part.strip()
    ):
        return True
    return False


@lru_cache(maxsize=16384)
def sanitize_product_name(raw: str) -> str:
    """归一化产品名，并剔除/修复误填的不合格项目名。"""
    from food_inspection.parser.text import normalize_product_name

    text = normalize_product_name(raw or "")
    if not text:
        return ""
    if looks_like_inspection_item_not_product(text):
        return ""
    recovered = recover_product_from_misplaced_failure_item(text)
    if recovered and not looks_like_inspection_item_not_product(recovered):
        text = recovered
    if looks_like_inspection_item_not_product(text):
        return ""
    return text


def split_company_embedded_product(raw: str) -> tuple[str, str]:
    """从「XX店使用的筷子」类受检单位字段拆出企业与产品。"""
    text = re.sub(r"\s+", "", _clean(raw))
    if not text:
        return "", ""
    for verb in ("使用的", "销售的", "经营的", "生产的", "购进的", "使用", "销售", "经营", "生产", "购进"):
        pos = text.find(verb)
        if pos <= 0:
            continue
        company = text[:pos].strip("（()、，, ")
        product = text[pos + len(verb) :].strip("（()、，,的 ")
        if company and product and not looks_like_inspection_item_not_product(product):
            return company, product
    return text, ""


def _item_field_is_usable(item_text: str, skip_verdict: frozenset[str]) -> bool:
    text = _clean(item_text)
    if not text or text in skip_verdict:
        return False
    for sep in FAILURE_CELL_SEPS:
        if sep in text:
            first = text.split(sep)[0].strip()
            if first and not _is_junk_failure_item(first):
                return True
    if _is_junk_failure_item(text):
        return False
    compact = _compact_failure_item_text(text)
    if _FAILURE_ITEM_MEASUREMENT.fullmatch(compact):
        return False
    if re.fullmatch(r"[\d.]+g/kg", compact, re.I):
        return False
    return True


def _parse_item_field(item_text: str) -> list[str]:
    found: list[str] = []
    for part in _split_multi_items(item_text):
        name = _apply_failure_item_alias(normalize_failure_item_name(part))
        if name and name not in found and not _is_org_failure_item_name(name):
            found.append(name)
    if found:
        return found
    single = _apply_failure_item_alias(normalize_failure_item_name(item_text))
    if single and not _is_org_failure_item_name(single):
        return [single]
    return [
        name
        for name in _recover_items_from_garbled_text(item_text)
        if name and not _is_org_failure_item_name(name)
    ]


def resolve_record_unqualified_item(record: dict[str, Any]) -> str:
    """从记录中解析不合格项目名称（含 reason 回退）。"""
    item = normalize_failure_item_name(record.get("unqualified_item") or "")
    if item:
        return item
    reason_items = _extract_failure_items_from_reason(record.get("reason") or "")
    if reason_items:
        return reason_items[0]
    reason_items = _extract_failure_items_from_reason(record.get("remark") or "")
    return reason_items[0] if reason_items else ""


def resolve_record_failure_items(record: dict[str, Any]) -> list[str]:
    """解析记录中的全部不合格项目名称。"""
    return list(
        _resolve_record_failure_items_cached(
            (record.get("unqualified_item") or "").strip(),
            (record.get("reason") or record.get("unqualified_reason") or "").strip(),
            (record.get("remark") or "").strip(),
            (record.get("unqualified_project_details") or "").strip(),
        )
    )


@lru_cache(maxsize=65536)
def _resolve_record_failure_items_cached(
    item_text: str,
    reason_text: str,
    remark_text: str,
    details_text: str,
) -> tuple[str, ...]:
    skip_verdict = frozenset({
        "合格", "不合格", "不符合", "未标注",
        "可接受", "不可接受", "接受", "满意", "符合", "通过", "未通过",
        "基本合格", "部分合格", "达标", "不达标",
    })
    found: list[str] = []

    item_text = _clean(item_text)
    reason_text = _clean(reason_text)
    remark_text = _clean(remark_text)
    details_text = _clean(details_text)

    if item_text and _is_junk_failure_item(item_text):
        if not _item_field_is_usable(item_text, skip_verdict):
            item_text = ""

    if item_text and _item_field_is_usable(item_text, skip_verdict):
        found = _parse_item_field(item_text)
        found = [
            name
            for name in found
            if name and not _is_junk_failure_item(name) and not _is_org_failure_item_name(name)
        ]

    if not found:
        for text in (reason_text, details_text, remark_text):
            if not text or text in skip_verdict or _is_junk_failure_item(text):
                continue
            for name in _extract_failure_items_from_reason(text):
                norm = normalize_failure_item_name(name)
                if norm and norm not in found and not _is_org_failure_item_name(norm):
                    found.append(norm)
            if found:
                break

    if not found:
        combined = "；".join(
            t
            for t in (item_text, reason_text, details_text, remark_text)
            if t and t not in skip_verdict and not _is_junk_failure_item(t)
        )
        if combined:
            for name in _extract_failure_items_from_reason(combined):
                norm = normalize_failure_item_name(name)
                if norm and norm not in found and not _is_org_failure_item_name(norm):
                    found.append(norm)
            if not found:
                recovered = _recover_items_from_garbled_text(combined)
                for name in recovered:
                    norm = normalize_failure_item_name(name)
                    if norm and norm not in found and not _is_org_failure_item_name(norm):
                        found.append(norm)

    return tuple(found)


def _is_food_category(text: str) -> bool:
    text = _clean(text)
    if not text:
        return False
    return any(text == cat or text.startswith(cat) for cat in FOOD_CATEGORY_KEYWORDS)


# 城市关键词 -> 所属省级行政区
CITY_PROVINCE_MAP: dict[str, str] = {
    "北京": "北京市", "上海": "上海市", "天津": "天津市", "重庆": "重庆市",
    "石家庄": "河北省", "太原": "山西省", "呼和浩特": "内蒙古自治区", "沈阳": "辽宁省",
    "长春": "吉林省", "哈尔滨": "黑龙江省", "南京": "江苏省", "杭州": "浙江省",
    "合肥": "安徽省", "福州": "福建省", "厦门": "福建省", "泉州": "福建省",
    "南昌": "江西省", "济南": "山东省", "郑州": "河南省", "武汉": "湖北省",
    "长沙": "湖南省", "广州": "广东省", "深圳": "广东省", "珠海": "广东省",
    "汕头": "广东省", "佛山": "广东省", "东莞": "广东省", "南宁": "广西壮族自治区",
    "海口": "海南省", "成都": "四川省", "贵阳": "贵州省", "昆明": "云南省",
    "拉萨": "西藏自治区", "西安": "陕西省", "兰州": "甘肃省", "西宁": "青海省",
    "银川": "宁夏回族自治区", "乌鲁木齐": "新疆维吾尔自治区",
}


def _normalize_province(name: str) -> str:
    if not name:
        return ""
    if name in ("北京", "上海", "天津", "重庆"):
        return name + "市"
    if name in ("内蒙古", "广西", "西藏", "宁夏", "新疆"):
        suffix = {
            "内蒙古": "内蒙古自治区",
            "广西": "广西壮族自治区",
            "西藏": "西藏自治区",
            "宁夏": "宁夏回族自治区",
            "新疆": "新疆维吾尔自治区",
        }
        return suffix[name]
    if name.endswith(("省", "市", "自治区")):
        return name
    return name + "省"


def _infer_province_from_city(city: str) -> str:
    if not city:
        return ""
    city_key = city.replace("市", "").replace("盟", "").replace("州", "")
    if city_key in CITY_PROVINCE_MAP:
        return CITY_PROVINCE_MAP[city_key]
    for key, province in CITY_PROVINCE_MAP.items():
        if key in city_key or city_key in key:
            return province
    return ""


def _extract_location_from_text(text: str) -> tuple[str, str]:
    text = _clean(text)
    if not text:
        return "", ""

    province = ""
    city = ""

    match = re.search(PROVINCE_PATTERN, text)
    if match:
        province = _normalize_province(match.group(1))
        if match.group(0) != match.group(1):
            province = match.group(0)

    city_match = CITY_PATTERN.search(text)
    if city_match:
        city = _sanitize_city_name(city_match.group(1))

    if not province or not city:
        for key in sorted(CITY_PROVINCE_MAP, key=len, reverse=True):
            if key not in text:
                continue
            candidate = _sanitize_city_name(key + "市")
            if candidate:
                city = candidate
            if not province:
                province = CITY_PROVINCE_MAP[key]
            if province and city:
                break

    if city and not province:
        province = _infer_province_from_city(city)

    return province, city


_DATA_ROOT_MARKER = "全国各省市食品安全监督抽查"
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:$")
_SKIP_PATH_PARTS = frozenset(
    {
        _DATA_ROOT_MARKER,
        "import_failed_files",
        "$RECYCLE.BIN",
        "System Volume Information",
    }
)


def _is_import_failed_path(filepath: str) -> bool:
    return "import_failed_files" in (filepath or "").replace("\\", "/")


def _extract_location_from_import_failed_name(filename: str) -> tuple[str, str]:
    """import_failed_files 内文件名通常形如：上海市_2024_2024_xxx.xls。"""
    base = re.sub(r"\.[^.]+$", "", filename or "")
    if not base:
        return "", ""

    parts = base.split("_")
    if len(parts) >= 2 and re.fullmatch(r"\d{4}", parts[1]):
        province, city = _extract_location_from_text(parts[0])
        if province:
            return province, city

    return _extract_location_from_text(base)


def source_relative_key(filepath: str) -> str:
    """跨平台统一文件标识（去掉盘符与数据根目录）。"""
    parts = _data_relative_parts(filepath)
    if not parts:
        return ""
    return "/".join(parts).casefold()


def _data_relative_parts(filepath: str) -> list[str]:
    """去掉盘符、数据根目录前缀，返回相对路径各段。"""
    if not filepath:
        return []

    rel = ""
    if DATA_ROOT and DATA_ROOT in filepath:
        rel = filepath.split(DATA_ROOT, 1)[1]
    else:
        norm = filepath.replace("\\", "/")
        if _DATA_ROOT_MARKER in norm:
            rel = norm.split(_DATA_ROOT_MARKER, 1)[1]
        else:
            rel = re.sub(r"^[A-Za-z]:[/\\]?", "", norm)

    parts = [part.strip() for part in re.split(r"[\\/]", rel) if part and part.strip()]
    while parts and _DRIVE_LETTER.fullmatch(parts[0]):
        parts = parts[1:]
    while parts and parts[0] in _SKIP_PATH_PARTS:
        parts = parts[1:]
    return parts


def _sanitize_folder_province(name: str) -> str:
    name = _clean(name)
    if not name or _DRIVE_LETTER.fullmatch(name):
        return ""
    if name in _SKIP_PATH_PARTS:
        return ""
    return name


def _extract_path_location_hints(filepath: str) -> tuple[str, str]:
    province = ""
    city = ""
    for part in _data_relative_parts(filepath):
        part_province, part_city = _extract_location_from_text(part)
        if part_province:
            province = part_province
        if part_city and _is_valid_city_name(part_city):
            city = part_city
    return province, city


def _extract_location_from_path(filepath: str) -> tuple[str, str]:
    if _is_import_failed_path(filepath):
        filename = re.split(r"[\\/]", filepath)[-1]
        province, city = _extract_location_from_import_failed_name(filename)
        if province:
            return province, city

    parts = _data_relative_parts(filepath)
    path_province = _sanitize_folder_province(parts[0]) if parts else ""
    path_city = _normalize_folder_city(parts[1]) if len(parts) > 1 else ""
    return path_province, path_city


_YEAR_FOLDER_RE = re.compile(r"^20\d{2}$")


def _extract_year_from_path(filepath: str) -> str:
    for part in _data_relative_parts(filepath):
        if _YEAR_FOLDER_RE.fullmatch(part):
            return part
    match = _YEAR_FOLDER_RE.search(os.path.basename(filepath))
    return match.group(0) if match else ""


def resolve_folder_province(record: dict[str, Any]) -> str:
    """从源文件文件夹路径解析省级目录名（与数据采集目录一致）。"""
    cached = _sanitize_folder_province(record.get("source_province") or "")
    filepath = record.get("source_file") or ""
    if filepath:
        path_province, _ = _extract_location_from_path(filepath)
        if path_province:
            return path_province
    return cached


def resolve_folder_city(record: dict[str, Any]) -> str:
    """从源文件文件夹路径解析市级目录名。"""
    return resolve_record_city(record)


def _merge_location(
    province_city: str,
    address: str,
    company: str,
    sampled_unit: str,
    filepath: str,
    path_province: str,
    path_city: str,
) -> tuple[str, str, str]:
    province = ""
    city = ""

    for text in (address, province_city, company, sampled_unit):
        part_province, part_city = _extract_location_from_text(text)
        if part_province:
            province = part_province
        if part_city:
            city = part_city
        if province and city:
            break

    path_hint_province, path_hint_city = _extract_path_location_hints(filepath)
    if not province:
        province = path_hint_province
    if not city:
        city = path_hint_city

    if not province:
        province = path_province
    if not city:
        city = path_city

    if city and not province:
        province = _infer_province_from_city(city)

    city = _sanitize_city_name(city)

    if province_city:
        display = province_city
        resolved = " / ".join(x for x in (province, city) if x)
        if province and province not in province_city:
            display = resolved
    else:
        display = " / ".join(x for x in (province, city) if x)

    return province, city, display
