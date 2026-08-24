"""工作表行解析与文件入口。"""

from __future__ import annotations

import os
from typing import Any, Iterator

from config import DATA_ROOT
from food_inspection.parser.classification import (
    _detect_file_mode,
    _detect_sheet_status,
    _enhance_column_map_for_supervision_verdict,
    _enhance_column_map_for_verdict,
    _infer_status_from_context,
    _parse_failure_from_inspection_result,
    _parse_verdict_status,
    _strip_test_items_unqualified_column,
    is_non_inspection_detail_file,
    is_planned_sampling_file,
)
from food_inspection.parser.food_scope import (
    is_food_product,
    is_non_food_inspection_file,
)
from food_inspection.parser.text import (
    collapse_wrapped_chinese_text,
    strip_product_enumeration_suffix,
)
from food_inspection.parser.category_fill import (
    backfill_categories_in_batch,
)
from food_inspection.parser.constants import SCAN_FILE_EXTENSIONS
from food_inspection.parser.fields import (
    _build_compliance_reason,
    _extract_location_from_path,
    _extract_year_from_path,
    _finalize_record_status,
    _maybe_correct_compact_combined_row,
    _merge_location,
    _parse_unqualified_detail,
    _resolve_row_status,
    _sheet_uses_verdict_column,
    _split_combined_failure,
    normalize_failure_item_name,
    resolve_unqualified_fields,
    sanitize_product_name,
)
from food_inspection.parser.disposal_narrative import (
    _is_disposal_narrative_file,
    is_skippable_disposal_zhengwen,
    parse_disposal_narrative_file,
    should_skip_risk_control_followup,
)
from food_inspection.parser.io import _read_all_sheets
from food_inspection.parser.layout import (
    _get_cell,
    _is_data_row,
    _is_date_like,
    _is_extended_data_row,
    _is_headerless_data_row,
    _is_sample_id_data_row,
    _resolve_company,
    _resolve_sheet_layout,
    normalize_company_name,
)
from food_inspection.parser.models import Record
from food_inspection.parser.text import _clean, is_invalid_company, normalize_product_name


def _resolve_sheet_status_for_filter(
    filepath: str,
    file_mode: str,
    sheet_name: str,
    rows: list[list[Any]],
    sheet_text: str,
) -> str | None:
    status = _detect_sheet_status(sheet_name, sheet_text, file_mode, rows)
    if status is None:
        status = _infer_status_from_context(filepath, sheet_text, rows)
    return status


def _filter_sheets_for_file_mode(
    filepath: str,
    file_mode: str,
    sheets: list[tuple[str, list[list[Any]], str]],
) -> list[tuple[str, list[list[Any]], str]]:
    """合格附件中常夹带旧版 Sheet1 不合格表，与主合格 sheet 重复；跳过这类残留 sheet。"""
    if file_mode != "qualified" or len(sheets) < 2:
        return sheets

    qualified_rows: list[tuple[str, int]] = []
    unqualified_generic: list[str] = []
    for sheet_name, rows, sheet_text in sheets:
        status = _resolve_sheet_status_for_filter(filepath, file_mode, sheet_name, rows, sheet_text)
        data_rows = max(len(rows) - 2, 0)
        if status == "qualified":
            qualified_rows.append((sheet_name, data_rows))
        elif status == "unqualified":
            generic = sheet_name.replace(" ", "")
            if generic.startswith("Sheet") or generic in {"复检", "复测"}:
                unqualified_generic.append(sheet_name)

    if not qualified_rows or not unqualified_generic:
        return sheets

    max_qualified = max(n for _, n in qualified_rows)
    skip: set[str] = set()
    for sheet_name in unqualified_generic:
        row_count = next(len(rows) for sn, rows, _ in sheets if sn == sheet_name)
        data_rows = max(row_count - 2, 0)
        if max_qualified >= 20 and data_rows <= 20 and max_qualified >= data_rows * 3:
            skip.add(sheet_name)

    if not skip:
        return sheets
    return [(sn, rows, text) for sn, rows, text in sheets if sn not in skip]


def _parse_sheet_rows(
    rows: list[list[Any]],
    status: str,
    filepath: str,
    sheet_name: str,
    path_province: str,
    path_city: str,
    file_mode: str = "unknown",
) -> list[Record]:
    layout = _resolve_sheet_layout(rows)
    if layout is None:
        return []

    header_idx, headers, col_map, layout_mode = layout
    if layout_mode in ("standard", "extended", "seq_disclosure", "sample_id_unqualified"):
        _enhance_column_map_for_verdict(headers, rows, header_idx, col_map)
        _enhance_column_map_for_supervision_verdict(headers, rows, header_idx, col_map)
        _strip_test_items_unqualified_column(headers, col_map, rows)
    allow_minimal = (
        layout_mode == "sample_id_unqualified"
        or (
            layout_mode == "seq_disclosure"
            and status == "unqualified"
            and "unqualified_item" in col_map
        )
    )
    if "product" not in col_map and "company" not in col_map and "sampled_unit" not in col_map:
        if not allow_minimal:
            return []

    records: list[Record] = []
    for row in rows[header_idx + 1 :]:
        cells = list(row)
        first = _clean(cells[0]) if cells else ""
        if not first:
            for pos in range(1, min(4, len(cells))):
                val = _clean(cells[pos])
                if val.replace(".", "").isdigit():
                    first = val
                    break
        if not first or first in ("序号", "编号", "备注", "抽样编号"):
            if not _is_extended_data_row(cells, col_map):
                continue
        if first.startswith("（声明") or first.startswith("声明"):
            break
        if layout_mode == "headerless":
            if not _is_headerless_data_row(cells):
                if records:
                    break
                continue
        elif layout_mode == "extended":
            if not _is_extended_data_row(cells, col_map):
                if records:
                    break
                continue
        elif layout_mode == "seq_disclosure":
            if not _is_data_row(cells, headers):
                if records:
                    break
                continue
        elif layout_mode == "sample_id_unqualified":
            if not _is_sample_id_data_row(cells, col_map):
                if records:
                    break
                continue
        elif not _is_data_row(cells, headers):
            if not _is_extended_data_row(cells, col_map):
                if records:
                    break
                continue

        company = _resolve_company(cells, col_map, headers)
        sampled_unit = normalize_company_name(_get_cell(cells, col_map, "sampled_unit"))
        product = _get_cell(cells, col_map, "product")
        if is_invalid_company(company):
            if not (
                product
                and sampled_unit
                and company == normalize_company_name(sampled_unit)
            ):
                continue
        province_city = _get_cell(cells, col_map, "province_city")
        address = collapse_wrapped_chinese_text(_get_cell(cells, col_map, "address"))
        manufacturer_address = collapse_wrapped_chinese_text(
            _get_cell(cells, col_map, "manufacturer_address")
        )
        category = _get_cell(cells, col_map, "category")
        remark = _get_cell(cells, col_map, "remark")
        compact_unqualified_raw = ""

        corrected = _maybe_correct_compact_combined_row(
            cells, company, sampled_unit, product, address, category
        )
        if corrected:
            company, sampled_unit, product, address, category, compact_unqualified_raw = corrected

        row_status = _resolve_row_status(status, cells, col_map, file_mode)
        row_status = _finalize_record_status(row_status, cells, col_map, status)

        if _is_date_like(product):
            continue

        product = sanitize_product_name(strip_product_enumeration_suffix(
            normalize_product_name(_get_cell(cells, col_map, "product") or product or category or "")
        ))
        if not product and layout_mode == "sample_id_unqualified":
            product = sanitize_product_name(_get_cell(cells, col_map, "sample_id") or category)
        if not product and layout_mode == "seq_disclosure" and category:
            product = sanitize_product_name(category)
        if not is_food_product(product, category):
            continue

        unqualified_item = ""
        reason = remark
        if row_status == "unqualified":
            verdict_text = _get_cell(cells, col_map, "inspection_result")
            item_from_verdict, reason_from_verdict = _parse_failure_from_inspection_result(
                verdict_text
            )
            verdict_driven = _sheet_uses_verdict_column(
                col_map, status
            ) and _parse_verdict_status(verdict_text) == "unqualified"
            if verdict_driven:
                unqualified_item = item_from_verdict
                reason = reason_from_verdict or (
                    f"不合格项目：{item_from_verdict}" if item_from_verdict else "检验结果：不合格"
                )
            elif compact_unqualified_raw:
                raw_item = compact_unqualified_raw
                item_part, measured, standard = _split_combined_failure(raw_item)
                unqualified_item = normalize_failure_item_name(item_part) or normalize_failure_item_name(raw_item)
                if standard or measured:
                    reason = _build_compliance_reason(unqualified_item, "", standard, measured)
                elif raw_item:
                    reason = _parse_unqualified_detail(raw_item)[1] or f"不合格项目：{unqualified_item}"
            else:
                unqualified_item, reason = resolve_unqualified_fields(cells, col_map, remark)
            if item_from_verdict and not unqualified_item:
                unqualified_item = item_from_verdict
            if reason_from_verdict and (
                not reason or reason_from_verdict != "检验结果：不合格"
            ):
                if len(reason_from_verdict) > len(reason or ""):
                    reason = reason_from_verdict
            if not reason and remark:
                reason = remark

        province, city, display_loc = _merge_location(
            province_city,
            address,
            company,
            sampled_unit,
            filepath,
            path_province,
            path_city,
        )

        if not company and not product:
            continue

        manufacturer = normalize_company_name(_get_cell(cells, col_map, "company"))
        serial_number = first
        if serial_number in ("序号", "编号", "备注", "抽样编号"):
            serial_number = _get_cell(cells, col_map, "sample_id")
        year = _extract_year_from_path(filepath)

        records.append(
            Record(
                status=row_status,
                company=company,
                product=product,
                province=province,
                city=city,
                province_city=display_loc,
                unqualified_item=unqualified_item,
                reason=reason,
                category=category,
                source_file=filepath,
                source_file_name=os.path.basename(filepath),
                source_sheet=sheet_name,
                source_province=path_province,
                source_city=path_city,
                sampled_unit=sampled_unit or company,
                manufacturer=manufacturer,
                address=address,
                manufacturer_address=manufacturer_address,
                serial_number=serial_number,
                year=year,
            )
        )

    return records


def parse_file(filepath: str) -> list[Record]:
    if is_non_inspection_detail_file(filepath) or is_non_food_inspection_file(filepath):
        return []

    if _is_disposal_narrative_file(filepath):
        if is_skippable_disposal_zhengwen(filepath):
            return []
        if should_skip_risk_control_followup(filepath):
            return []
        records = parse_disposal_narrative_file(filepath) or []
        return records

    if is_planned_sampling_file(filepath):
        return []

    filename = os.path.basename(filepath)
    file_mode = _detect_file_mode(filename)
    path_province, path_city = _extract_location_from_path(filepath)
    all_records: list[Record] = []

    sheet_entries = [(sheet_name, rows, sheet_text) for sheet_name, rows, sheet_text in _read_all_sheets(filepath) if rows]
    sheet_entries = _filter_sheets_for_file_mode(filepath, file_mode, sheet_entries)

    for sheet_name, rows, sheet_text in sheet_entries:
        status = _detect_sheet_status(sheet_name, sheet_text, file_mode, rows)
        if status is None:
            status = _infer_status_from_context(filepath, sheet_text, rows)
        if status is None:
            continue

        all_records.extend(
            _parse_sheet_rows(
                rows, status, filepath, sheet_name, path_province, path_city, file_mode
            )
        )

    if all_records:
        backfill_categories_in_batch(all_records)
        return all_records

    if "_正文" in filename or filename.lower().endswith(".pdf"):
        if not is_skippable_disposal_zhengwen(filepath):
            narrative = parse_disposal_narrative_file(filepath)
            if narrative:
                backfill_categories_in_batch(narrative)
                return narrative
    return all_records



def iter_excel_files(root: str = DATA_ROOT) -> Iterator[str]:
    if not os.path.isdir(root):
        return
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.startswith("~$"):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in SCAN_FILE_EXTENSIONS:
                yield os.path.join(dirpath, name)
