"""分析无法解析的 Excel 文件原因。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir

import os
import sys
from collections import Counter, defaultdict

from food_inspection.parser import (
    _build_column_map,
    _clean,
    _find_header_row,
    is_planned_sampling_file,
    iter_excel_files,
    parse_file,
)
from food_inspection.parser.classification import _detect_file_mode, _detect_sheet_status
from food_inspection.parser.io import _read_all_sheets
from food_inspection.parser.layout import _get_cell, _resolve_company



def diagnose_sheets(filepath: str) -> str:
    """仅根据工作表结构诊断，不调用 parse_file（避免 PDF OCR 等耗时路径）。"""
    filename = os.path.basename(filepath)
    file_mode = _detect_file_mode(filename)
    sheets = _read_all_sheets(filepath)
    if not sheets:
        return "read_failed_or_empty"

    reasons: list[str] = []
    for sheet_name, rows, sheet_text in sheets:
        if not rows:
            reasons.append("empty_sheet")
            continue

        status = _detect_sheet_status(sheet_name, sheet_text, file_mode)
        if status is None:
            reasons.append("unknown_status")
            continue

        header_idx = _find_header_row(rows)
        if header_idx is None:
            first_cells = [_clean(c) for c in rows[0][:6]] if rows else []
            if any("序号" in c for row in rows[:10] for c in [_clean(x) for x in row]):
                reasons.append("header_not_standard")
            else:
                reasons.append("no_header_row")
            continue

        headers = [_clean(c) for c in rows[header_idx]]
        col_map = _build_column_map(headers)
        if "product" not in col_map and "company" not in col_map and "sampled_unit" not in col_map:
            reasons.append("missing_key_columns")
            continue

        data_rows = 0
        skipped_no_name = 0
        for row in rows[header_idx + 1 :]:
            cells = list(row)
            first = _clean(cells[0]) if cells else ""
            if not first or first in ("序号", "备注"):
                continue
            if first.startswith("（声明") or first.startswith("声明"):
                break
            if not first.replace(".", "").isdigit():
                if data_rows:
                    break
                continue
            data_rows += 1
            company = _resolve_company(cells, col_map)
            product = _get_cell(cells, col_map, "product")
            if not company and not product:
                skipped_no_name += 1

        if data_rows == 0:
            reasons.append("no_data_rows")
        elif skipped_no_name == data_rows:
            reasons.append("all_rows_no_company_product")
        else:
            reasons.append("rows_filtered")

    if not reasons:
        return "unknown"

    return Counter(reasons).most_common(1)[0][0]


def diagnose_file(filepath: str, *, retry_parse: bool = True) -> str:
    if not os.path.isfile(filepath):
        return "file_missing"

    if is_planned_sampling_file(filepath):
        return "planned_skip"

    if retry_parse:
        try:
            records = parse_file(filepath)
            if records:
                return "ok"
        except Exception:
            return "exception"

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return "no_data_rows"

    return diagnose_sheets(filepath)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    files = list(iter_excel_files())
    reason_counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)

    for i, filepath in enumerate(files, 1):
        reason = diagnose_file(filepath)
        reason_counter[reason] += 1
        if len(samples[reason]) < 5:
            samples[reason].append(filepath)

        if i % 200 == 0:
            print(f"已分析 {i}/{len(files)}...", flush=True)

    total = len(files)
    ok = reason_counter.get("ok", 0)
    print(f"\n总计 Excel: {total}")
    print(f"解析成功: {ok} ({ok/total*100:.1f}%)")
    print(f"未解析: {total - ok} ({(total-ok)/total*100:.1f}%)\n")

    labels = {
        "planned_skip": "计划抽检清单/工作方案（已排除，非实际抽检结果）",
        "ok": "解析成功",
        "read_failed_or_empty": "文件无法读取或完全空白",
        "unknown_status": "无法识别合格/不合格（汇总表、说明页等）",
        "no_header_row": "找不到标准表头（首列不是「序号」）",
        "header_not_standard": "有「序号」但缺少产品名称列",
        "missing_key_columns": "表头缺少产品/单位等关键列",
        "no_data_rows": "有表头但没有数据行",
        "all_rows_no_company_product": "有数据行但公司名和产品名都为空",
        "rows_filtered": "数据行被过滤规则跳过",
        "exception": "读取时发生异常",
        "file_missing": "文件不存在",
        "empty_sheet": "空工作表",
        "unknown": "其他原因",
    }

    print("原因分布：")
    for reason, count in reason_counter.most_common():
        if reason == "ok":
            continue
        label = labels.get(reason, reason)
        print(f"  {label}: {count} ({count/total*100:.1f}%)")
        for path in samples[reason][:3]:
            print(f"    - {path}")

    content_lines = [f"总计 {total}，成功 {ok}，未解析 {total-ok}\n"]
    for reason, count in reason_counter.most_common():
        if reason == "ok":
            continue
        content_lines.append(f"{labels.get(reason, reason)}: {count}\n")
        for path in samples[reason]:
            content_lines.append(f"  {path}\n")
        content_lines.append("\n")
    content = "".join(content_lines)

    for name in ("未解析文件分析.txt", "未解析原因汇总.txt"):
        ensure_output_dir()
        out = os.path.join(OUTPUT_DIR, name)
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"\n详细列表已写入: {out}")
            break
        except OSError as exc:
            print(f"\n写入 {out} 失败: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
