"""导出未入库（787 等）文件完整路径，按原因分组。"""

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
    "ok": "当前代码可解析(需重试空文件列表)",
    "read_failed_or_empty": "PDF/Excel 读不出或无可识别表格",
    "unknown_status": "无法识别合格/不合格",
    "no_header_row": "找不到标准表头",
    "header_not_standard": "有序号但缺产品列",
    "missing_key_columns": "缺少产品/单位列",
    "no_data_rows": "有表头无数据行",
    "all_rows_no_company_product": "有行但公司/产品皆空",
    "rows_filtered": "数据行被过滤",
    "exception": "读取异常",
    "empty_sheet": "空工作表",
    "unknown": "其他",
}

CACHE_PATH = CACHE_FILE
OUT_PATH = os.path.join(OUTPUT_DIR, "未入库787文件-路径清单.txt")


def _quick_bucket(filepath: str) -> str:
    name = os.path.basename(filepath).replace(" ", "")
    ext = os.path.splitext(filepath)[1].lower()
    if "检验项目" in name or "本次检验" in name:
        return "quick_检验项目PDF"
    if "小知识" in name:
        return "quick_科普说明PDF"
    if "抽检结果" in name and "合格" not in name and "不合格" not in name:
        return "quick_你点我检汇总PDF"
    if ext == ".pdf":
        return "quick_其他PDF"
    if ext in (".xlsx", ".xls") and (
        name.startswith("Cp") or name.startswith("Cq") or len(name) < 20
    ):
        return "quick_乱码/短名Excel"
    if ext in (".xlsx", ".xls"):
        return "quick_普通Excel"
    return "quick_其他"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from food_inspection.parser import (
        is_non_inspection_detail_file,
        is_planned_sampling_file,
        iter_excel_files,
    )
    from food_inspection.scan import collect_indexed_paths, normalize_path

    with open(CACHE_PATH, encoding="utf-8") as f:
        cached = json.load(f)

    parsed_paths, empty_paths = collect_indexed_paths(cached)
    empty_only = empty_paths - parsed_paths

    unindexed: list[str] = []
    for filepath in iter_excel_files():
        if is_planned_sampling_file(filepath):
            continue
        norm = normalize_path(filepath)
        if norm not in parsed_paths:
            unindexed.append(filepath)

    by_quick: dict[str, list[str]] = defaultdict(list)
    by_reason: dict[str, list[str]] = defaultdict(list)
    by_province: Counter[str] = Counter()
    ext_counter: Counter[str] = Counter()

    print(f"未入库文件: {len(unindexed)}，其中在空文件列表: {len(empty_only)}")
    print("正在诊断（仅未入库，已入库不分析）...")

    for i, filepath in enumerate(unindexed, 1):
        parts = filepath.replace(os.path.normpath(os.path.dirname(__file__)), "").split(os.sep)
        # 路径形如 Z:\...\省份\城市\...
        rel = filepath
        try:
            from food_inspection.parser import DATA_ROOT

            if rel.startswith(DATA_ROOT):
                parts = rel[len(DATA_ROOT) :].strip("\\/").split(os.sep)
        except Exception:
            parts = rel.split(os.sep)
        prov = parts[0] if parts else "未知"
        by_province[prov] += 1
        ext_counter[os.path.splitext(filepath)[1].lower() or "(无)"] += 1

        qb = _quick_bucket(filepath)
        by_quick[qb].append(filepath)

        if is_non_inspection_detail_file(filepath):
            by_reason["non_detail_skip"].append(filepath)
        else:
            reason = diagnose_file(filepath)
            by_reason[reason].append(filepath)

        if i % 50 == 0 or i == len(unindexed):
            print(f"  {i}/{len(unindexed)}", flush=True)

    lines: list[str] = [
        "未入库文件路径清单（供升级解析逻辑参考）",
        "=" * 72,
        f"合计: {len(unindexed)}",
        f"已入库跳过: {len(parsed_paths)}",
        f"缓存空文件标记: {len(empty_only)}",
        "",
        "【扩展名】",
    ]
    for ext, n in ext_counter.most_common():
        lines.append(f"  {ext}: {n}")
    lines.extend(["", "【省份 TOP20】"])
    for prov, n in by_province.most_common(20):
        lines.append(f"  {prov}: {n}")

    lines.extend(["", "【快速归类（看文件名）】", "-" * 72])
    for key in sorted(by_quick.keys()):
        items = by_quick[key]
        lines.append(f"\n## {key} ({len(items)} 个)")
        for p in items:
            lines.append(p)

    lines.extend(["", "", "【诊断归类（程序检测）】", "-" * 72])
    reason_titles = {
        "non_detail_skip": "建议排除-非抽检明细附件",
        **REASON_LABELS,
    }
    order = [
        "ok",
        "non_detail_skip",
        "read_failed_or_empty",
        "unknown_status",
        "empty_sheet",
        "no_data_rows",
        "missing_key_columns",
        "no_header_row",
        "header_not_standard",
        "all_rows_no_company_product",
        "rows_filtered",
        "exception",
        "unknown",
    ]
    for key in order:
        items = by_reason.get(key, [])
        if not items:
            continue
        title = reason_titles.get(key, key)
        lines.append(f"\n## {title} ({len(items)} 个)")
        for p in items:
            lines.append(p)

    for key, items in by_reason.items():
        if key in order or not items:
            continue
        lines.append(f"\n## {key} ({len(items)} 个)")
        for p in items:
            lines.append(p)

    text = "\n".join(lines) + "\n"
    ensure_output_dir()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\n已写入: {OUT_PATH}")
    print("诊断统计:")
    for key in order:
        n = len(by_reason.get(key, []))
        if n:
            print(f"  {reason_titles.get(key, key)}: {n}")


if __name__ == "__main__":
    main()
