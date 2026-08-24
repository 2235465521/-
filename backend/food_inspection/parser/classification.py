"""文件分类与合格/不合格状态识别。"""

from __future__ import annotations

import os
import re
from typing import Any

from food_inspection.parser.constants import (
    COMBINED_FAILURE_CELL,
    FAILURE_CELL_SEPS,
    FAILURE_HINT_CELL,
    QUALIFIED_MARKERS,
    UNQUALIFIED_MARKERS,
)
from food_inspection.parser.text import _clean, _normalize_header


def _has_failure_sep(text: str) -> bool:
    text = text or ""
    if "||" in text or "║" in text or "‖" in text:
        return True
    if any(sep in text for sep in ("|", "｜", "丨")):
        compact = re.sub(r"\s+", "", text)
        if re.search(
            r"(%vol|m[lI]/|ml/|/盒|/瓶|/袋|计量称重|净含量)",
            compact,
            re.IGNORECASE,
        ):
            return False
        return True
    return False


def _has_qualified_marker(text: str) -> bool:
    compact = text.replace(" ", "")
    return any(m.replace(" ", "") in compact for m in QUALIFIED_MARKERS)


def _has_unqualified_marker(text: str) -> bool:
    compact = text.replace(" ", "")
    return any(m.replace(" ", "") in compact for m in UNQUALIFIED_MARKERS)


COMBINED_PUBLICATION_PATTERNS = (
    "合格（不合格）",
    "合格(不合格",
    "合格和不合格",
    "合格及不合格",
    "合 格 和 不 合 格",
)


def _is_combined_publication(filename: str) -> bool:
    """「合格（不合格）食品公示信息」类：同一表内混合合格与不合格产品。"""
    compact = filename.replace(" ", "")
    return any(p.replace(" ", "") in compact for p in COMBINED_PUBLICATION_PATTERNS)


def _detect_file_mode(filename: str) -> str:
    compact = filename.replace(" ", "")
    if _is_combined_publication(filename):
        return "combined"
    if "合格表" in compact and "不合格" not in compact:
        return "qualified"
    if "不合格表" in compact:
        return "unqualified"
    if "明细表" in compact or "抽检信息" in compact:
        return "combined"
    if "汇总表" in compact:
        return "summary"
    if "不合格" in filename or "不 合 格" in filename:
        return "unqualified"
    if "合格" in filename or "合 格" in filename:
        return "qualified"
    return "unknown"


PLANNED_SAMPLING_PATH_MARKERS = (
    "工作方案",
    "工作计划",
    "任务分配表",
    "工作计划表",
    "抽检工作方案",
)


def is_planned_sampling_file(filepath: str) -> bool:
    """计划抽检清单/工作方案等非实际抽检结果，不参与统计。"""
    name = os.path.basename(filepath)
    compact_name = name.replace(" ", "")
    compact = (name + filepath).replace(" ", "")

    # 湛江「你点我检」等：抽检产品信息（无合格/不合格字样）
    # 东莞/韶关「食品监督抽检产品信息」：表内含结论列，合格与不合格混合，需解析
    if "抽检产品信息" in compact_name:
        if "食品监督抽检产品信息" in compact_name:
            return False
        if "合格" not in compact_name and "不合格" not in compact_name:
            return True
    # 漳州等：食品监督抽检产品信息表（非合格/不合格分表）
    if "产品信息表" in compact_name:
        if "合格" not in compact_name and "不合格" not in compact_name:
            return True
    if "授权使用" in name and "商标" in name:
        return True
    return any(m.replace(" ", "") in compact for m in PLANNED_SAMPLING_PATH_MARKERS)


NON_INSPECTION_DETAIL_MARKERS = (
    "本次检验项目",
    "本次检测项目",
    "检验项目.pdf",
    "检测项目.pdf",
    "小知识",
    "附件1：本次检验",
    "附件1 本次检验",
    "附件2：关于部分检验项目",
    "附件2.关于部分检验项目",
    "附件2：关于部分检测项目",
    "附件2.关于部分检测项目",
)


def is_non_inspection_detail_file(filepath: str) -> bool:
    """非合格/不合格明细（检验项目说明、科普页、汇总说明等），无需解析。"""
    name = os.path.basename(filepath).replace(" ", "")
    compact = (name + filepath).replace(" ", "")
    if any(m.replace(" ", "") in compact for m in NON_INSPECTION_DETAIL_MARKERS):
        if not any(k in compact for k in ("合格产品", "不合格产品", "合格样品", "不合格样品")):
            return True
    if "抽检结果" in name and "合格" not in name and "不合格" not in name:
        return True
    if (
        "不合格检验项目说明" in compact
        or "不合格检测项目说明" in compact
        or "检验项目说明" in compact
        or "检测项目说明" in compact
        or "检验项目的说明" in compact
        or "检测项目的说明" in compact
        or "部分检验项目" in compact
        or "部分检测项目" in compact
    ):
        return True
    if "风险提示" in compact:
        return True
    return False


def _is_product_info_table_file(filepath: str) -> bool:
    """韶关/东莞等「食品监督抽检产品信息(.xlsx)」：以结论列判定合格/不合格。"""
    name = os.path.basename(filepath).replace(" ", "")
    return "食品监督抽检产品信息" in name


def _strip_test_items_unqualified_column(
    headers: list[str],
    col_map: dict[str, int],
    rows: list[list[Any]],
) -> None:
    """「检验项目」列为检测清单，不是不合格项目，不得映射为 unqualified_item。"""
    normalized = {_normalize_header(h): i for i, h in enumerate(headers) if _clean(h)}
    test_items_idx = normalized.get("检验项目")
    if test_items_idx is None:
        return
    if col_map.get("unqualified_item") == test_items_idx:
        del col_map["unqualified_item"]


def _infer_status_from_context(
    filepath: str,
    sheet_text: str,
    rows: list[list[Any]] | None,
) -> str | None:
    """【新增兜底】乱码文件名/无表名时，从路径与表头推断合格或不合格。"""
    path_compact = filepath.replace(" ", "")
    head = sheet_text[:800]

    if _is_product_info_table_file(filepath):
        if rows and _sheet_has_verdict_column(rows):
            return "result_column"
        return "product_info_qualified"

    if rows and _sheet_has_verdict_column(rows):
        return "result_column"

    if "明细表" in path_compact or "抽检信息" in path_compact:
        return "combined"
    if _is_combined_publication(os.path.basename(filepath)):
        return "combined"

    if _has_unqualified_marker(path_compact) and "合格" not in path_compact.replace("不合格", ""):
        return "unqualified"
    if _has_qualified_marker(path_compact) or _has_qualified_marker(head):
        return "qualified"

    for idx in range(min(8, len(rows or []))):
        cells = [_clean(c) for c in rows[idx]]
        joined = "".join(cells)
        if not any(k in joined for k in ("食品名称", "样品名称", "产品名称")):
            continue
        if "检验结果" in joined or "监督抽检结果" in joined:
            return "result_column"
        if "不合格项目" in joined:
            if any(k in path_compact for k in ("不合格信息", "不合格产品", "不合格样品")):
                return "unqualified"
            return "combined"
        if "标称生产企业" in joined or "被抽样单位" in joined or "抽样编号" in joined:
            return "qualified"
    return None


def _is_verdict_value(text: str) -> bool:
    text = _clean(text)
    if not text:
        return False
    if _parse_verdict_status(text):
        return True
    if text in ("合格", "符合", "达标", "部分合格"):
        return True
    if text.startswith("不合格") or text.startswith("不符合"):
        return True
    if text in ("不合格", "不符合"):
        return True
    return False


def _parse_verdict_status(text: str) -> str | None:
    """从检验结论/检验结果单元格判断合格/不合格（韶关等：仅本列含不合格才计不合格）。"""
    text = _clean(text)
    if not text:
        return None
    if "不合格样品" in text or "不合格报告" in text:
        return "unqualified"
    if "合格样品" in text or "合格报告" in text:
        return "qualified"
    head = re.split(r"[/／、;；|]", text, maxsplit=1)[0].strip()
    if head in ("合格", "符合", "达标") or (
        head.startswith("合格") and "不合格" not in head and not _has_failure_sep(head)
    ):
        return "qualified"
    if text in ("合格", "符合", "达标") or (
        text.startswith("合格") and "不合格" not in text and not _has_failure_sep(text)
    ):
        return "qualified"
    if (
        head.startswith("不合格")
        or head.startswith("不符合")
        or head == "不合格"
        or text.startswith("不合格")
        or text.startswith("不符合")
        or text == "不合格"
    ):
        return "unqualified"
    return None


def _parse_failure_from_inspection_result(text: str) -> tuple[str, str]:
    """从不合格检验结果文本提取项目与说明（如 不合格：吡虫啉‖7.47mg/kg‖≤0.2mg/kg）。"""
    from food_inspection.parser.fields import (
        _build_compliance_reason,
        _extract_unit,
        _split_combined_failure,
        normalize_failure_item_name,
    )

    text = _clean(text)
    if _parse_verdict_status(text) != "unqualified":
        return "", ""

    detail = re.sub(r"^不合格[：:\s/／、]*", "", text)
    detail = re.sub(r"^不符合[：:\s/／、]*", "", detail).strip()
    if not detail:
        return "", "检验结果：不合格"

    parts = re.split(r"[;；]+", detail)
    items: list[str] = []
    reasons: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        item_part, measured, standard = _split_combined_failure(part)
        unit = _extract_unit(measured) or _extract_unit(standard)
        name = normalize_failure_item_name(item_part) or normalize_failure_item_name(part)
        if name:
            items.append(name)
        if measured or standard:
            reasons.append(_build_compliance_reason(name, unit, standard, measured))
        elif name:
            reasons.append(f"不合格项目：{name}")

    item_text = "、".join(dict.fromkeys(items)) if items else ""
    if not item_text and detail:
        first_seg = detail
        for sep in FAILURE_CELL_SEPS:
            if sep in first_seg:
                first_seg = first_seg.split(sep)[0]
                break
        item_text = normalize_failure_item_name(first_seg)
    reason_text = "；".join(reasons) if reasons else detail
    return item_text, reason_text


def _sample_column_values(
    rows: list[list[Any]], header_idx: int, col_idx: int, limit: int = 20
) -> list[str]:
    values: list[str] = []
    for row in rows[header_idx + 1 : header_idx + 1 + limit]:
        if col_idx < len(row):
            val = _clean(row[col_idx])
            if val:
                values.append(val)
    return values


def _column_is_verdict_column(values: list[str]) -> bool:
    if not values:
        return False
    verdict_hits = sum(1 for v in values if _is_verdict_value(v))
    return verdict_hits >= max(2, len(values) // 3)


def _enhance_column_map_for_verdict(
    headers: list[str],
    rows: list[list[Any]],
    header_idx: int,
    col_map: dict[str, int],
) -> None:
    """识别「检验结果」结论列，或备注列中的合格/不合格标记。"""
    if "inspection_result" in col_map:
        idx = col_map["inspection_result"]
        if _column_is_verdict_column(_sample_column_values(rows, header_idx, idx)):
            return
        del col_map["inspection_result"]

    normalized = {_normalize_header(h): i for i, h in enumerate(headers) if _clean(h)}
    for key in ("检验结果", "抽检结果", "检测结论", "结论", "检验结论", "检验结论/不合格项目"):
        if key not in normalized:
            continue
        idx = normalized[key]
        if _column_is_verdict_column(_sample_column_values(rows, header_idx, idx)):
            col_map["inspection_result"] = idx
            if col_map.get("measured_value") == idx:
                del col_map["measured_value"]
            return

    remark_idx = col_map.get("remark")
    if remark_idx is not None and _column_is_verdict_column(
        _sample_column_values(rows, header_idx, remark_idx)
    ):
        col_map["inspection_result"] = remark_idx


def _enhance_column_map_for_supervision_verdict(
    headers: list[str],
    rows: list[list[Any]],
    header_idx: int,
    col_map: dict[str, int],
) -> None:
    """【新增兜底】识别「监督抽检结果」等原规则未覆盖的结论列。"""
    if "inspection_result" in col_map:
        return

    normalized = {_normalize_header(h): i for i, h in enumerate(headers) if _clean(h)}
    for key in ("监督抽检结果",):
        if key not in normalized:
            continue
        idx = normalized[key]
        if _column_is_verdict_column(_sample_column_values(rows, header_idx, idx)):
            col_map["inspection_result"] = idx
            return

    for key, idx in normalized.items():
        if key.endswith("抽检结果") and "不合格项目" not in key:
            if _column_is_verdict_column(_sample_column_values(rows, header_idx, idx)):
                col_map["inspection_result"] = idx
                return


def _sheet_has_verdict_column(rows: list[list[Any]]) -> bool:
    from food_inspection.parser.layout import _build_column_map, _find_header_row

    header_idx = _find_header_row(rows)
    if header_idx is None:
        return False
    headers = [_clean(c) for c in rows[header_idx]]
    col_map = _build_column_map(headers)
    _enhance_column_map_for_verdict(headers, rows, header_idx, col_map)
    return "inspection_result" in col_map


def _detect_sheet_status(
    sheet_name: str,
    sheet_text: str,
    file_mode: str,
    rows: list[list[Any]] | None = None,
) -> str | None:
    name = sheet_name.replace(" ", "")
    head = sheet_text[:800]

    if rows and _sheet_has_verdict_column(rows):
        return "result_column"

    if "不合格" in name and "合格" not in name.replace("不合格", ""):
        return "unqualified"
    if "合格" in name and "不合格" not in name:
        return "qualified"

    # 不合格优先，避免「不合格」中的「合格」误判
    if _has_unqualified_marker(head):
        return "unqualified"
    if _has_qualified_marker(head):
        return "qualified"

    if file_mode in ("qualified", "unqualified"):
        return file_mode
    if file_mode == "combined":
        return "combined"
    if file_mode == "summary":
        return "result_column"
    return None


SAMPLE_ID_PATTERN = re.compile(r"^[DS]BJ\d+", re.IGNORECASE)
DATE_LIKE_PATTERN = re.compile(
    r"^(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}|\d{4}\.\d{1,2}\.\d{1,2}|\d{4}/\d{1,2}/\d{1,2})$"
)

# 无表头明细：序号|抽样编号|标称企业|…|被抽样单位|地址|食品名称|…
HEADERLESS_FIXED_COL_MAP: dict[str, int] = {
    "company": 2,
    "sampled_unit": 4,
    "address": 5,
    "product": 6,
    "category": 9,
}

