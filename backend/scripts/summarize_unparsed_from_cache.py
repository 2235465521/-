"""根据缓存跳过已解析文件，仅汇总未入库文件的原因。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir

import json
import os
import sys
from collections import Counter, defaultdict

from scripts.analyze_unparsed_files import diagnose_file

REASON_LABELS = {
    "planned_skip": "计划抽检清单/工作方案（已排除）",
    "ok": "诊断可解析但缓存未入库（建议增量重扫）",
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
from food_inspection.parser import DATA_ROOT, is_planned_sampling_file, iter_excel_files
from food_inspection.scan import collect_indexed_paths, normalize_path

CACHE_PATH = CACHE_FILE
OUT_PATH = os.path.join(OUTPUT_DIR, "未解析原因汇总.txt")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.path.isfile(CACHE_PATH):
        print("未找到 data_cache.json，请先运行 rescan_cache.py")
        sys.exit(1)

    with open(CACHE_PATH, encoding="utf-8") as f:
        cached = json.load(f)

    parsed_paths, empty_paths = collect_indexed_paths(cached)
    stats = cached.get("stats", {})
    scan_info = cached.get("scan_info", {})

    all_files = list(iter_excel_files())
    planned = 0
    unparsed_files: list[str] = []
    for filepath in all_files:
        if is_planned_sampling_file(filepath):
            planned += 1
            continue
        norm = normalize_path(filepath)
        if norm not in parsed_paths:
            unparsed_files.append(filepath)

    reason_counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    by_province: dict[str, Counter[str]] = defaultdict(Counter)

    total_unparsed = len(unparsed_files)
    print(f"数据根目录: {DATA_ROOT}")
    print(f"缓存扫描时间: {scan_info.get('scanned_at', '未知')}")
    print(f"全库文件: {len(all_files)}，计划清单(排除): {planned}")
    print(f"已入库(跳过): {len(parsed_paths)}")
    print(f"待分析未入库: {total_unparsed}\n")

    for i, filepath in enumerate(unparsed_files, 1):
        reason = diagnose_file(filepath)
        reason_counter[reason] += 1
        if len(samples[reason]) < 8:
            samples[reason].append(filepath)
        parts = filepath.replace(DATA_ROOT, "").strip("\\/").split(os.sep)
        prov = parts[0] if parts else "未知"
        by_province[prov][reason] += 1

        if i % 50 == 0 or i == total_unparsed:
            print(f"  分析 {i}/{total_unparsed}...", flush=True)

    lines: list[str] = []
    lines.append("未解析文件原因汇总（仅未入库文件，已解析的不重复分析）")
    lines.append("=" * 60)
    lines.append(f"生成时间: {scan_info.get('scanned_at', '')}")
    lines.append(f"全库文件数: {len(all_files)}")
    lines.append(f"计划清单(未纳入统计): {planned}")
    lines.append(f"已入库文件数: {stats.get('parsed_files', len(parsed_paths))}")
    lines.append(f"未入库文件数: {total_unparsed}")
    lines.append(f"（界面 有效数据 约 {stats.get('parsed_files')}/{stats.get('total_files')}）")
    lines.append("")
    lines.append("原因分布（按文件数）:")
    lines.append("-" * 60)

    for reason, count in reason_counter.most_common():
        if reason == "ok":
            continue
        pct = count / total_unparsed * 100 if total_unparsed else 0
        label = REASON_LABELS.get(reason, reason)
        lines.append(f"  [{count:4d}] ({pct:5.1f}%) {label}")
        for path in samples[reason][:5]:
            lines.append(f"        {path}")
        lines.append("")

    ok_unexpected = reason_counter.get("ok", 0)
    if ok_unexpected:
        lines.append(f"  注意: 有 {ok_unexpected} 个文件诊断可解析但缓存未入库，可增量重扫补入。")
        lines.append("")

    lines.append("按省份未入库数量 TOP15:")
    lines.append("-" * 60)
    prov_totals = [(p, sum(c.values())) for p, c in by_province.items()]
    for prov, n in sorted(prov_totals, key=lambda x: -x[1])[:15]:
        lines.append(f"  {prov}: {n}")

    text = "\n".join(lines) + "\n"
    print("\n" + text)

    ensure_output_dir()
    for name in (OUT_PATH, os.path.join(OUTPUT_DIR, "未解析文件分析.txt")):
        try:
            with open(name, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"已写入: {name}")
            break
        except OSError as exc:
            print(f"写入 {name} 失败: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
