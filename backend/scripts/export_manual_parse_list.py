"""导出仍未入库文件路径，区分「可排除附件」与「需人工提供解析逻辑」。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir

import json
import os
import sys
from collections import Counter, defaultdict

from scripts.analyze_unparsed_files import REASON_LABELS, diagnose_file
from food_inspection.parser import DATA_ROOT, is_non_inspection_detail_file, is_planned_sampling_file, iter_excel_files
from food_inspection.scan import collect_indexed_paths, normalize_path

CACHE_PATH = CACHE_FILE
OUT_PATH = os.path.join(OUTPUT_DIR, "待人工解析-路径清单.txt")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE_PATH, encoding="utf-8") as f:
        cached = json.load(f)

    parsed_paths, _ = collect_indexed_paths(cached)
    unparsed: list[str] = []
    for filepath in iter_excel_files():
        if is_planned_sampling_file(filepath):
            continue
        if normalize_path(filepath) not in parsed_paths:
            unparsed.append(filepath)

    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    reason_counter: Counter[str] = Counter()

    for i, filepath in enumerate(unparsed, 1):
        if is_non_inspection_detail_file(filepath):
            groups["exclude_non_detail"].append((filepath, "非抽检明细附件"))
            continue

        reason = diagnose_file(filepath)
        reason_counter[reason] += 1
        label = REASON_LABELS.get(reason, reason)

        if reason == "ok":
            bucket = "retry_pending"
        elif reason in ("read_failed_or_empty",) and filepath.lower().endswith(".pdf"):
            bucket = "pdf_need_logic"
        elif filepath.lower().endswith((".xlsx", ".xls")):
            bucket = "excel_need_logic"
        elif filepath.lower().endswith(".pdf"):
            bucket = "pdf_need_logic"
        else:
            bucket = "other_need_logic"

        groups[bucket].append((filepath, label))

        if i % 50 == 0 or i == len(unparsed):
            print(f"  归类 {i}/{len(unparsed)}...", flush=True)

    lines: list[str] = [
        "待处理文件路径清单",
        "=" * 72,
        f"未入库合计: {len(unparsed)}",
        f"  其中建议排除(检验项目/小知识/汇总说明): {len(groups['exclude_non_detail'])}",
        f"  其中需您提供解析逻辑: {sum(len(groups[k]) for k in groups if k != 'exclude_non_detail')}",
        "",
        "【一、建议排除 — 非合格/不合格明细，一般无需统计】",
        "-" * 72,
    ]
    for path, note in groups["exclude_non_detail"]:
        lines.append(f"{path}")
        lines.append(f"    说明: {note}")
        lines.append("")

    lines.extend(
        [
            "【二、Excel — 需您提供表头/列映射或特殊规则】",
            "-" * 72,
        ]
    )
    for path, note in groups["excel_need_logic"]:
        lines.append(f"{path}")
        lines.append(f"    诊断: {note}")
        lines.append("")

    lines.extend(
        [
            "【三、PDF — 需您提供版式说明（若为扫描件请说明）】",
            "-" * 72,
        ]
    )
    for path, note in groups["pdf_need_logic"]:
        lines.append(f"{path}")
        lines.append(f"    诊断: {note}")
        lines.append("")

    if groups["retry_pending"]:
        lines.extend(
            [
                "【四、程序已能解析 — 将自动补扫入库】",
                "-" * 72,
            ]
        )
        for path, note in groups["retry_pending"]:
            lines.append(path)

    if groups["other_need_logic"]:
        lines.extend(["【五、其他】", "-" * 72])
        for path, note in groups["other_need_logic"]:
            lines.append(f"{path}  ({note})")

    lines.extend(["", "诊断统计(不含已排除附件):", "-" * 72])
    for reason, count in reason_counter.most_common():
        lines.append(f"  {REASON_LABELS.get(reason, reason)}: {count}")

    text = "\n".join(lines) + "\n"
    ensure_output_dir()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\n已写入: {OUT_PATH}")
    print(f"  排除附件: {len(groups['exclude_non_detail'])}")
    print(f"  Excel需规则: {len(groups['excel_need_logic'])}")
    print(f"  PDF需规则: {len(groups['pdf_need_logic'])}")
    print(f"  可自动补扫: {len(groups['retry_pending'])}")


if __name__ == "__main__":
    main()
