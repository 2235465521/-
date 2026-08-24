"""表头检测、列映射与版式识别。"""

from __future__ import annotations

import re
from typing import Any

from food_inspection.parser.classification import (
    DATE_LIKE_PATTERN,
    HEADERLESS_FIXED_COL_MAP,
    SAMPLE_ID_PATTERN,
    _enhance_column_map_for_supervision_verdict,
    _enhance_column_map_for_verdict,
    _is_verdict_value,
    _parse_verdict_status,
)

_SAMPLE_ID_HEADER_LABELS = frozenset(
    {"抽样编号", "样品编号", "样品条码", "条码编号"}
)
from food_inspection.parser.constants import COLUMN_ALIASES
from food_inspection.parser.text import (
    _clean,
    _normalize_header,
    is_health_food_sheet,
    normalize_company_name,
)


def _is_seq_header_label(cell: str) -> bool:
    return _clean(cell) in ("序号", "编号")


def _is_sample_id_header_label(cell: str) -> bool:
    return _clean(cell) in _SAMPLE_ID_HEADER_LABELS


def _is_date_like(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    if DATE_LIKE_PATTERN.match(text):
        return True
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", text))


def _is_headerless_sample_row(cells: list[Any]) -> bool:
    if len(cells) < 7:
        return False
    seq = _clean(cells[0])
    sample_id = _clean(cells[1])
    if not (seq.replace(".", "").isdigit() and SAMPLE_ID_PATTERN.match(sample_id)):
        return False
    company = _clean(cells[4])
    product = _clean(cells[6])
    if not company or not product:
        return False
    if product in ("食品名称", "样品名称", "规格型号"):
        return False
    return True


def _detect_headerless_layout(rows: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    for idx in range(min(8, len(rows))):
        if _is_headerless_sample_row(list(rows[idx])):
            return idx, dict(HEADERLESS_FIXED_COL_MAP)
    return None


def _rows_have_seq_header(rows: list[list[Any]]) -> bool:
    for idx in range(min(5, len(rows))):
        cells = [_clean(c) for c in rows[idx]]
        if any(_is_seq_header_label(c) for c in cells):
            return True
    return False


def _detect_seq_disclosure_layout(
    rows: list[list[Any]],
) -> tuple[int, list[str], dict[str, int]] | None:
    """【新增兜底】有「序号」表头但无产品名称列的简化公示表（避免误入无表头规则）。"""
    for idx in range(min(8, len(rows))):
        cells = [_clean(c) for c in rows[idx]]
        if not cells or not any(_is_seq_header_label(c) for c in cells):
            continue
        joined = "".join(cells)
        if any(k in joined for k in ("食品名称", "样品名称", "产品名称")):
            return None
        col_map = _build_column_map(cells)
        if not col_map and not any("不合格项目" in c for c in cells):
            continue
        return idx, cells, col_map
    return None


def _is_compact_combined_row(cells: list[Any]) -> bool:
    """九江等合并公示表：不合格段缺抽样编号，列整体左移。"""
    from food_inspection.parser.fields import _cell_has_combined_failure

    if len(cells) < 8:
        return False
    first = _clean(cells[0])
    if not first.replace(".", "").isdigit():
        return False
    if SAMPLE_ID_PATTERN.match(first):
        return False
    if len(cells) > 1 and SAMPLE_ID_PATTERN.match(_clean(cells[1])):
        return False
    if not _cell_has_combined_failure(_clean(cells[7])):
        return False
    product = _clean(cells[5])
    return bool(product) and not _is_date_like(product)


def _extract_compact_combined_fields(cells: list[Any]) -> dict[str, str]:
    return {
        "company": _clean(cells[3]),
        "sampled_unit": _clean(cells[3]),
        "address": _clean(cells[4]),
        "product": _clean(cells[5]),
        "category": _clean(cells[8]) if len(cells) > 8 else "",
        "unqualified_raw": _clean(cells[7]),
    }


def _row_has_product_header(cells: list[str]) -> bool:
    joined = "".join(cells)
    if any(k in joined for k in ("食品名称", "样品名称", "产品名称")):
        return True
    normalized = "".join(_normalize_header(c) for c in cells if _clean(c))
    return any(k in normalized for k in ("食品名称", "样品名称", "产品名称"))


def _row_has_standard_header_markers(cells: list[str]) -> bool:
    return any(_is_seq_header_label(c) for c in cells) or any(
        _is_sample_id_header_label(c) for c in cells
    )


def _find_header_row(rows: list[list[Any]], max_scan: int = 25) -> int | None:
    """标准表头：含「序号/编号」或「抽样编号」且含食品/样品/产品名称列。"""
    for idx in range(min(max_scan, len(rows))):
        cells = [_clean(c) for c in rows[idx]]
        if not cells or not _row_has_standard_header_markers(cells):
            continue
        if _row_has_product_header(cells):
            return idx
    return None


def _find_extended_header_row(rows: list[list[Any]], max_scan: int = 25) -> int | None:
    """扩展表头（仅作兜底）：抽样编号 / 被抽样单位 + 产品名称，无序号。"""
    for idx in range(min(max_scan, len(rows))):
        cells = [_clean(c) for c in rows[idx]]
        if not cells or any(_is_seq_header_label(c) for c in cells):
            continue
        joined = "".join(cells)
        has_product_col = any(k in joined for k in ("食品名称", "样品名称", "产品名称"))
        if not has_product_col:
            continue
        normalized = {_normalize_header(c) for c in cells if _clean(c)}
        if "抽样编号" in normalized or "抽样编号" in cells:
            return idx
        if any("被抽样单位" in c for c in normalized):
            return idx
    return None


def _resolve_sheet_layout(
    rows: list[list[Any]],
) -> tuple[int, list[str], dict[str, int], str] | None:
    """解析表结构：标准表头 -> 扩展表头 -> 有序号简化公示表(新增) -> 无表头固定列。"""
    header_idx = _find_header_row(rows)
    if header_idx is not None:
        headers = [_clean(c) for c in rows[header_idx]]
        col_map = _build_column_map(headers)
        if "product" in col_map or "company" in col_map or "sampled_unit" in col_map:
            return header_idx, headers, col_map, "standard"

    header_idx = _find_extended_header_row(rows)
    if header_idx is not None:
        headers = [_clean(c) for c in rows[header_idx]]
        col_map = _build_column_map(headers)
        if "product" in col_map or "company" in col_map or "sampled_unit" in col_map:
            return header_idx, headers, col_map, "extended"

    sample_layout = _detect_sample_id_unqualified_layout(rows)
    if sample_layout is not None:
        header_idx, headers, col_map = sample_layout
        return header_idx, headers, col_map, "sample_id_unqualified"

    seq_layout = _detect_seq_disclosure_layout(rows)
    if seq_layout is not None:
        header_idx, headers, col_map = seq_layout
        return header_idx, headers, col_map, "seq_disclosure"

    layout = _detect_headerless_layout(rows)
    if layout is not None:
        start_idx, col_map = layout
        return start_idx - 1, [], col_map, "headerless"

    return None


def _detect_sample_id_unqualified_layout(
    rows: list[list[Any]],
) -> tuple[int, list[str], dict[str, int]] | None:
    """【新增兜底】无序号、无样品名，仅有抽样编号+不合格项目（九江等）。"""
    for idx in range(min(8, len(rows))):
        cells = [_clean(c) for c in rows[idx]]
        if not cells or any(_is_seq_header_label(c) for c in cells):
            continue
        joined = "".join(cells)
        if "抽样编号" not in joined or "不合格项目" not in joined:
            continue
        if any(k in joined for k in ("食品名称", "样品名称", "产品名称")):
            continue
        col_map = _build_column_map(cells)
        if "unqualified_item" in col_map:
            return idx, cells, col_map
    return None


def _is_sample_id_data_row(cells: list[Any], col_map: dict[str, int]) -> bool:
    sample_id = _get_cell(cells, col_map, "sample_id")
    if not sample_id and cells:
        sample_id = _clean(cells[0])
    return bool(sample_id and SAMPLE_ID_PATTERN.match(sample_id))


def _find_seq_column(headers: list[str]) -> int | None:
    for idx, header in enumerate(headers):
        if _is_seq_header_label(header):
            return idx
    return None


def _is_data_row(cells: list[Any], headers: list[str]) -> bool:
    """标准数据行：序号列为数字，或抽样编号列有值，或首列为数字/抽样编号。"""
    seq_idx = _find_seq_column(headers)
    if seq_idx is not None and seq_idx < len(cells):
        val = _clean(cells[seq_idx])
        if val and val.replace(".", "").isdigit():
            return True

    for idx, header in enumerate(headers):
        if _is_sample_id_header_label(header) and idx < len(cells):
            val = _clean(cells[idx])
            if val and SAMPLE_ID_PATTERN.match(val):
                return True

    for pos in (0, 1, 2):
        if pos < len(cells):
            val = _clean(cells[pos])
            if not val:
                continue
            if val.replace(".", "").isdigit():
                return True
            if SAMPLE_ID_PATTERN.match(val):
                return True
    return False


def _is_extended_data_row(cells: list[Any], col_map: dict[str, int]) -> bool:
    """扩展表头数据行：被抽样单位 + 产品均有值。"""
    unit = _get_cell(cells, col_map, "sampled_unit")
    product = _get_cell(cells, col_map, "product")
    if not unit or not product:
        return False
    if unit in ("被抽样单位名称", "序号", "编号", "抽样编号"):
        return False
    return True


def _is_headerless_data_row(cells: list[Any]) -> bool:
    return _is_headerless_sample_row(cells)


def _build_column_map(headers: list[str]) -> dict[str, int]:
    normalized = {_normalize_header(h): i for i, h in enumerate(headers) if _clean(h)}
    mapping: dict[str, int] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in normalized:
                mapping[field] = normalized[key]
                break
        if field not in mapping:
            fuzzy_idx = _fuzzy_column_index(normalized, field)
            if fuzzy_idx is not None:
                mapping[field] = fuzzy_idx
    return mapping


def _is_sampling_agency_header(key: str) -> bool:
    """抽样/抽检单位 = 执行抽检的机构，不是被抽检商户。"""
    compact = re.sub(r"\s+", "", key)
    if compact in ("抽样单位", "抽样单位名称", "抽检单位", "抽检单位名称"):
        return True
    if compact.startswith(("抽样单位", "抽检单位")) and not compact.startswith(("被抽样", "被抽检")):
        return True
    return False


def _fuzzy_column_index(normalized: dict[str, int], field: str) -> int | None:
    if field == "unqualified_item":
        for key, idx in normalized.items():
            if "不合格项目" in key and any(
                token in key for token in ("||", "║", "检出", "检验结果", "标准")
            ):
                return idx
        for key, idx in normalized.items():
            if key in ("不合格项目", "不合格项目名称", "不合格项"):
                return idx
            if key.startswith("不合格项目"):
                return idx
    if field == "item_unit":
        for key, idx in normalized.items():
            if "不合格项目单位" in key:
                return idx
    if field == "standard_value":
        for key, idx in normalized.items():
            if "标准规定值" in key or key in ("标准值", "限值", "产品明示标准"):
                return idx
    if field == "measured_value":
        for key, idx in normalized.items():
            if key in ("实测值", "检出值", "测定值", "检测值"):
                return idx
            if "检验结果" in key and "不合格" in key:
                # 合并列「不合格项目║检验结果║标准值」由 unqualified_item 拆分，勿当作独立实测列
                if "不合格项目" in key and any(
                    token in key for token in ("||", "║", "‖", "|", "丨", "｜")
                ):
                    continue
                return idx
    if field == "product":
        for key, idx in normalized.items():
            if any(token in key for token in ("食品名称", "样品名称", "产品名称")):
                return idx
    if field == "company":
        for key, idx in normalized.items():
            if "地址" in key or "所在" in key:
                continue
            if any(
                token in key
                for token in ("标称生产企业", "标称生产单位", "生产企业名称", "生产单位", "生产者名称")
            ):
                return idx
            if key in ("企业名称", "生产企业"):
                return idx
    if field == "manufacturer_address":
        for key, idx in normalized.items():
            if any(
                token in key
                for token in (
                    "标称生产企业地址",
                    "标识生产企业地址",
                    "生产企业地址",
                    "生产单位地址",
                    "标称生产单位地址",
                )
            ):
                return idx
    if field == "address":
        for key, idx in normalized.items():
            if any(token in key for token in ("受检单位地址", "被抽样单位地址", "被抽样地址")):
                return idx
    if field == "sampled_unit":
        for key, idx in normalized.items():
            if "地址" in key or "所在" in key or key.endswith(("省", "地市", "市", "县", "区", "地区", "州", "盟")):
                continue
            if _is_sampling_agency_header(key):
                continue
            if "被抽样单位" in key and "名称" in key:
                return idx
        for key, idx in normalized.items():
            if "地址" in key or "所在" in key or key.endswith(("省", "地市", "市", "县", "区", "地区", "州", "盟")) or _is_sampling_agency_header(key):
                continue
            if key in (
                "受检单位名称",
                "受检单位",
                "被抽样单位",
                "被抽检单位",
                "被抽检单位名称",
                "被抽查单位",
                "被抽查单位名称",
                "被检单位名称",
                "被检单位",
            ):
                return idx
            if any(token in key for token in ("受检单位", "被抽样单位", "被抽检单位", "被检单位")):
                return idx
        for key, idx in normalized.items():
            if key == "单位名称" and not _is_sampling_agency_header(key):
                return idx
    return None


def _get_cell(row: list[Any], mapping: dict[str, int], field: str) -> str:
    idx = mapping.get(field)
    if idx is None or idx >= len(row):
        return ""
    return _clean(row[idx])


def _resolve_company(
    row: list[Any],
    col_map: dict[str, int],
    headers: list[str] | None = None,
) -> str:
    """解析统计用单位名：保健食品表优先被抽样单位；否则标称企业为空时用被抽样单位。"""
    company_raw = _get_cell(row, col_map, "company")
    sampled_unit = normalize_company_name(_get_cell(row, col_map, "sampled_unit"))
    company = normalize_company_name(company_raw)

    if headers and is_health_food_sheet(headers) and sampled_unit:
        return sampled_unit

    unit_hint = re.compile(r"(公司|店|厂|中心|食堂|餐饮|超市|商行|有限|个体)")
    if company and sampled_unit:
        if not unit_hint.search(company) and unit_hint.search(sampled_unit):
            return sampled_unit
        if len(company) < 8 <= len(sampled_unit):
            return sampled_unit
    if company:
        return company
    return sampled_unit
