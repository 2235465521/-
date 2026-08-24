"""导出仍未入库文件：按原因分组 + Excel 表头样例，供用户补充解析规则。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir

import json
import os
import sys
from collections import Counter, defaultdict

from scripts.analyze_unparsed_files import diagnose_file

REASON_LABELS = {
    "planned_skip": "计划清单(已排除)",
    "ok": "程序可解析(需重试空文件)",
    "read_failed_or_empty": "无法读取或空白",
    "unknown_status": "无法识别合格/不合格",
    "no_header_row": "找不到表头",
    "header_not_standard": "有序号缺产品列",
    "missing_key_columns": "缺少产品/单位列",
    "no_data_rows": "有表头无数据",
    "all_rows_no_company_product": "公司/产品皆空",
    "rows_filtered": "数据行被过滤",
    "exception": "读取异常",
    "empty_sheet": "空工作表",
    "unknown": "其他",
}
from food_inspection.parser import (
    DATA_ROOT,
    _build_column_map,
    _clean,
    _find_header_row,
    _read_all_sheets,
    is_non_inspection_detail_file,
    is_planned_sampling_file,
    iter_excel_files,
)
from food_inspection.scan import collect_indexed_paths, normalize_path

CACHE = CACHE_FILE
OUT_SUMMARY = os.path.join(OUTPUT_DIR, "待升级解析规则-汇总.txt")
OUT_PATHS = os.path.join(OUTPUT_DIR, "待升级解析规则-路径清单.txt")


def _excel_header_hint(filepath: str) -> str:
    try:
        sheets = _read_all_sheets(filepath)
    except Exception as exc:
        return f"(读取失败: {exc})"
    for _sn, rows, _st in sheets:
        if not rows:
            continue
        idx = _find_header_row(rows)
        if idx is not None:
            headers = [_clean(c) for c in rows[idx]]
            col = _build_column_map(headers)
            mapped = ", ".join(f"{k}={headers[v]}" for k, v in sorted(col.items()) if v < len(headers))
            return f"表头行{idx + 1}: {' | '.join(h for h in headers if h)[:200]}; 识别列: {mapped or '无'}"
        for i, row in enumerate(rows[:8]):
            cells = [_clean(c) for c in row[:12]]
            if any(cells):
                return f"前8行第{i + 1}行: {' | '.join(cells)}"
    return "(无内容)"


def _bucket_for_export(filepath: str, reason: str) -> str:
    if is_non_inspection_detail_file(filepath):
        return "00_建议排除_非明细附件"
    if reason == "ok":
        return "01_程序可解析_待重试入库"
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return f"02_PDF_{REASON_LABELS.get(reason, reason)}"
    return f"03_Excel_{REASON_LABELS.get(reason, reason)}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE, encoding="utf-8") as f:
        cached = json.load(f)

    parsed_paths, _ = collect_indexed_paths(cached)
    unparsed: list[str] = []
    for filepath in iter_excel_files():
        if is_planned_sampling_file(filepath):
            continue
        if normalize_path(filepath) not in parsed_paths:
            unparsed.append(filepath)

    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    reason_counter: Counter[str] = Counter()
    prov_counter: Counter[str] = Counter()

    print(f"未入库 {len(unparsed)} 个，开始诊断...", flush=True)
    for i, filepath in enumerate(unparsed, 1):
        reason = diagnose_file(filepath)
        reason_counter[reason] += 1
        parts = filepath.replace(DATA_ROOT, "").strip("\\/").split(os.sep)
        prov = parts[0] if parts else "未知"
        prov_counter[prov] += 1

        hint = ""
        if filepath.lower().endswith((".xls", ".xlsx")) and reason not in ("ok",):
            hint = _excel_header_hint(filepath)

        bucket = _bucket_for_export(filepath, reason)
        groups[bucket].append((filepath, REASON_LABELS.get(reason, reason), hint))

        if i % 40 == 0 or i == len(unparsed):
            print(f"  {i}/{len(unparsed)}", flush=True)

    need_rules = sum(
        len(v) for k, v in groups.items() if not k.startswith("00_") and not k.startswith("01_")
    )

    summary_lines = [
        "待升级解析规则 — 汇总",
        "=" * 72,
        f"未入库文件总数: {len(unparsed)}",
        f"需您提供规则(不含排除/可自动重试): {need_rules}",
        f"已入库: {len(parsed_paths)}",
        "",
        "【按诊断原因统计】",
    ]
    for reason, count in reason_counter.most_common():
        summary_lines.append(f"  {REASON_LABELS.get(reason, reason)}: {count}")

    summary_lines.extend(["", "【按省份 TOP15】"])
    for prov, count in prov_counter.most_common(15):
        summary_lines.append(f"  {prov}: {count}")

    summary_lines.extend(
        [
            "",
            "【说明】",
            "  - 00_建议排除: 检验项目/小知识等，一般不必做抽检统计",
            "  - 01_程序可解析: 跑 python rescan_cache.py --retry-empty 可入库",
            "  - 02_PDF / 03_Excel: 请按分组提供表头列名或样例规则",
            "",
            "详细路径见: " + OUT_PATHS,
        ]
    )

    path_lines = [
        "待升级解析规则 — 完整路径（按分组）",
        "=" * 72,
        f"共 {len(unparsed)} 个文件",
        "",
    ]

    for bucket in sorted(groups.keys()):
        items = groups[bucket]
        path_lines.append("")
        path_lines.append(f"## {bucket} ({len(items)} 个)")
        path_lines.append("-" * 72)
        for filepath, label, hint in items:
            path_lines.append(filepath)
            path_lines.append(f"    诊断: {label}")
            if hint:
                path_lines.append(f"    表头: {hint}")
            path_lines.append("")

    ensure_output_dir()
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines) + "\n")
    with open(OUT_PATHS, "w", encoding="utf-8") as f:
        f.write("\n".join(path_lines) + "\n")

    print(f"\n已写入:\n  {OUT_SUMMARY}\n  {OUT_PATHS}")
    for bucket in sorted(groups.keys()):
        print(f"  {bucket}: {len(groups[bucket])}")


if __name__ == "__main__":
    main()
