"""导出公司名为空/占位符的记录，便于分析解析原因。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from food_inspection.parser import (
    _build_column_map,
    _clean,
    _find_header_row,
    _get_cell,
    _read_all_sheets,
    is_invalid_company,
    normalize_company_name,
)

CACHE = Path(CACHE_FILE)
OUT = Path(OUTPUT_DIR) / "公司名为空记录导出.xlsx"

CACHE_COLUMNS = [
    "导出序号",
    "数据状态",
    "当前解析公司名",
    "产品名称",
    "不合格项目",
    "原因",
    "分类",
    "抽样省市",
    "数据省市",
    "源文件",
    "源工作表",
]

SOURCE_EXTRA = [
    "标称生产企业名称(原始)",
    "被抽样单位名称(原始)",
    "标称生产企业地址(原始)",
    "被抽样单位地址(原始)",
    "建议采用公司名",
    "源表匹配说明",
]


def _load_bad_records() -> list[dict[str, Any]]:
    with CACHE.open(encoding="utf-8") as f:
        data = json.load(f)

    rows: list[dict[str, Any]] = []
    for status in ("qualified", "unqualified"):
        for record in data.get(status, []):
            if not is_invalid_company(record.get("company")):
                continue
            rows.append(
                {
                    "数据状态": "合格" if status == "qualified" else "不合格",
                    "当前解析公司名": (record.get("company") or "").strip(),
                    "产品名称": record.get("product") or "",
                    "不合格项目": record.get("unqualified_item") or "",
                    "原因": record.get("reason") or "",
                    "分类": record.get("category") or "",
                    "抽样省市": record.get("province_city") or record.get("province") or "",
                    "数据省市": " / ".join(
                        x
                        for x in (
                            record.get("source_province") or "",
                            record.get("source_city") or "",
                        )
                        if x
                    ),
                    "源文件": record.get("source_file_name") or "",
                    "源工作表": record.get("source_sheet") or "",
                    "_source_file": record.get("source_file") or "",
                    "_source_sheet": record.get("source_sheet") or "",
                    "_product": record.get("product") or "",
                }
            )
    return rows


def _style_header(ws, row: int, col_count: int) -> None:
    fill = PatternFill("solid", fgColor="1F4E79")
    font = Font(bold=True, color="FFFFFF", size=11)
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(style="thin", color="B4C6E7")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = align
        cell.border = border


def _style_body(ws, start_row: int, end_row: int, col_count: int) -> None:
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    alt_fill = PatternFill("solid", fgColor="F2F7FB")
    for row in range(start_row, end_row + 1):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=row, column=col)
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if row % 2 == 0:
                cell.fill = alt_fill


def _autosize_columns(ws, headers: list[str], data_rows: list[dict[str, str]]) -> None:
    for col_idx, header in enumerate(headers, 1):
        letter = get_column_letter(col_idx)
        max_len = len(header)
        for row in data_rows:
            value = str(row.get(header, ""))
            max_len = max(max_len, min(len(value), 60))
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 52)


def _enrich_from_source(rows: list[dict[str, Any]]) -> None:
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        path = row.get("_source_file") or ""
        if path:
            by_file[path].append(row)

    for source_file, file_rows in by_file.items():
        path = Path(source_file)
        if not path.exists():
            for row in file_rows:
                row["源表匹配说明"] = "源文件不存在"
            continue

        targets = {
            (row.get("_source_sheet") or "", row.get("_product") or ""): row
            for row in file_rows
        }

        for sheet_name, sheet_rows, _ in _read_all_sheets(source_file):
            header_idx = _find_header_row(sheet_rows)
            if header_idx is None:
                continue
            col_map = _build_column_map(sheet_rows[header_idx])

            for cells in sheet_rows[header_idx + 1 :]:
                first = _clean(cells[0]) if cells else ""
                if not first:
                    continue
                if first in ("序号", "备注"):
                    continue
                if first.startswith("（声明") or first.startswith("声明"):
                    break
                if not first.replace(".", "").isdigit():
                    continue

                product = _get_cell(cells, col_map, "product")
                key = (sheet_name, product)
                target = targets.get(key)
                if not target:
                    continue

                company_raw = _get_cell(cells, col_map, "company")
                sampled_raw = _get_cell(cells, col_map, "sampled_unit")
                address_raw = _get_cell(cells, col_map, "address")
                suggested = normalize_company_name(company_raw) or normalize_company_name(sampled_raw)

                target["标称生产企业名称(原始)"] = company_raw
                target["被抽样单位名称(原始)"] = sampled_raw
                target["标称生产企业地址(原始)"] = address_raw
                target["被抽样单位地址(原始)"] = _get_cell(cells, col_map, "address")
                target["建议采用公司名"] = suggested
                if suggested:
                    target["源表匹配说明"] = "标称企业为空，可回退到被抽样单位"
                elif not _clean(company_raw) and not _clean(sampled_raw):
                    target["源表匹配说明"] = "标称企业与被抽样单位均为空"
                elif _clean(company_raw) in ("/", "／") or str(company_raw).strip() == "／":
                    target["源表匹配说明"] = "标称企业为斜杠占位符"
                else:
                    target["源表匹配说明"] = "需人工核对源表"


def export() -> Path:
    rows = _load_bad_records()
    _enrich_from_source(rows)

    headers = CACHE_COLUMNS + SOURCE_EXTRA
    export_rows: list[dict[str, str]] = []
    for idx, row in enumerate(rows, 1):
        export_row = {"导出序号": str(idx)}
        for key in headers[1:]:
            export_row[key] = str(row.get(key, ""))
        export_rows.append(export_row)

    wb = Workbook()

    ws = wb.active
    ws.title = "公司名为空明细"
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    title = ws.cell(row=1, column=1, value=f"公司名为空/占位符记录导出（共 {len(export_rows)} 条）")
    title.font = Font(bold=True, size=14, color="1F4E79")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
    note = ws.cell(
        row=2,
        column=1,
        value=(
            "说明：当前解析公司名为空、/、／、无 等占位符的记录。"
            "已尝试从源 Excel 回填「标称生产企业名称」「被抽样单位名称」原始值。"
            "修复解析逻辑后请重新扫描数据。"
        ),
    )
    note.font = Font(size=10, color="666666")
    note.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[2].height = 36

    header_row = 3
    for col, name in enumerate(headers, 1):
        ws.cell(row=header_row, column=col, value=name)
    _style_header(ws, header_row, len(headers))

    data_start = header_row + 1
    for i, row in enumerate(export_rows, 1):
        excel_row = data_start + i - 1
        for col, key in enumerate(headers, 1):
            ws.cell(row=excel_row, column=col, value=row.get(key, ""))

    if export_rows:
        _style_body(ws, data_start, data_start + len(export_rows) - 1, len(headers))
        ws.auto_filter.ref = f"A3:{get_column_letter(len(headers))}{data_start + len(export_rows) - 1}"
    ws.freeze_panes = "A4"
    _autosize_columns(ws, headers, export_rows)

    summary = wb.create_sheet("按源文件汇总")
    counter = Counter((r.get("源文件") or "(未知文件)", r.get("数据状态")) for r in export_rows)
    by_file: Counter[str] = Counter()
    raw_values: Counter[str] = Counter()
    for r in export_rows:
        by_file[r.get("源文件") or "(未知文件)"] += 1
        raw_values[r.get("当前解析公司名") or "(空白)"] += 1

    summary["A1"] = "源文件"
    summary["B1"] = "记录数"
    summary["C1"] = "合格"
    summary["D1"] = "不合格"
    _style_header(summary, 1, 4)
    row_idx = 2
    for file_name in sorted(by_file):
        q = counter.get((file_name, "合格"), 0)
        u = counter.get((file_name, "不合格"), 0)
        summary.cell(row=row_idx, column=1, value=file_name)
        summary.cell(row=row_idx, column=2, value=q + u)
        summary.cell(row=row_idx, column=3, value=q)
        summary.cell(row=row_idx, column=4, value=u)
        row_idx += 1

    summary.column_dimensions["A"].width = 48
    summary.column_dimensions["B"].width = 12
    summary.column_dimensions["C"].width = 10
    summary.column_dimensions["D"].width = 10

    stats = wb.create_sheet("占位符统计")
    stats["A1"] = "当前解析公司名"
    stats["B1"] = "条数"
    _style_header(stats, 1, 2)
    for idx, (name, count) in enumerate(raw_values.most_common(), 2):
        stats.cell(row=idx, column=1, value=name)
        stats.cell(row=idx, column=2, value=count)
    stats.column_dimensions["A"].width = 24
    stats.column_dimensions["B"].width = 12

    ensure_output_dir()
    wb.save(OUT)
    return OUT


if __name__ == "__main__":
    path = export()
    print(path)
