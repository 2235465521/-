"""一次性输出未解析文件原因汇总（读缓存，不依赖 Z 盘）。"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir


def region(path: str) -> str:
    rel = path.split(":", 1)[-1].lstrip("\\/")
    parts = [x for x in rel.split(os.sep) if x]
    return parts[1] if len(parts) > 1 else "未知"


def tag_failed(path: str) -> str:
    base = os.path.basename(path).replace(" ", "")
    ext = os.path.splitext(path)[1].lower()
    if "监督抽检信息" in base:
        return "上海式监督抽检信息表(.xls)"
    if ext == ".xls":
        return "老版.xls(非上海命名)"
    if ext == ".xlsx":
        return "xlsx读取失败"
    if ext == ".pdf":
        return "pdf读取失败"
    return "其他"


def tag_empty(path: str) -> str:
    base = os.path.basename(path).replace(" ", "")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "PDF附件(打开但抽不出数据行)"
    if ext == ".xls":
        if base.endswith("_1.xls"):
            return "通告正文副本(_1.xls)"
        return "xls(表头/版式不识别)"
    if ext == ".xlsx":
        return "xlsx(表头/版式不识别)"
    return "其他"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE_FILE, encoding="utf-8") as f:
        cached = json.load(f)

    stats = cached.get("stats", {})
    scan = cached.get("scan_info", {})
    failed = scan.get("failed_file_paths", []) or []
    empty = scan.get("empty_file_paths", []) or []
    unparsed = stats.get("total_files", 0) - stats.get("parsed_files", 0)
    pct = unparsed / stats["total_files"] * 100 if stats.get("total_files") else 0

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("未解析文件原因汇总 (来自 data_cache.json)")
    lines.append(f"扫描时间: {scan.get('scanned_at', '未知')}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("【总体口径】")
    lines.append(
        f"  全库文件: {stats.get('total_files', 0) + stats.get('skipped_planned_files', 0) + stats.get('skipped_non_detail_files', 0)}"
    )
    lines.append(f"  计划清单(已排除，未计入分母): {stats.get('skipped_planned_files', 0)}")
    lines.append(f"  非明细附件(已排除): {stats.get('skipped_non_detail_files', 0)}")
    lines.append(f"  纳入统计(界面分母): {stats.get('total_files', 0)}")
    lines.append(f"  有效数据(已解析): {stats.get('parsed_files', 0)}")
    lines.append(f"  未解析合计: {unparsed} ({pct:.1f}%)")
    lines.append(f"    · 读取异常 failed: {len(failed)}")
    lines.append(f"    · 无数据行 empty: {stats.get('empty_files', 0)}")
    lines.append("")

    lines.append(f"【一、读取异常 {len(failed)} 个 — 文件打不开或解析抛错】")
    for tag, count in Counter(tag_failed(p) for p in failed).most_common():
        lines.append(f"  [{count:4d}] ({count / len(failed) * 100:5.1f}%) {tag}")
    lines.append("  省份 TOP8:")
    for reg, count in Counter(region(p) for p in failed).most_common(8):
        lines.append(f"    {reg}: {count}")
    lines.append("  样例:")
    for path in failed[:6]:
        lines.append(f"    - {os.path.basename(path)}  ({region(path)})")
    lines.append("")

    lines.append(
        f"【二、尝试过但无数据 empty 路径库 {len(empty)} 条，当前统计 {stats.get('empty_files', 0)} 个】"
    )
    lines.append("  (能打开文件，但表头/数据行识别失败，未提取到任何批次)")
    for tag, count in Counter(tag_empty(p) for p in empty).most_common():
        lines.append(f"  [{count:4d}] ({count / len(empty) * 100:5.1f}%) {tag}")
    lines.append("  省份 TOP8:")
    for reg, count in Counter(region(p) for p in empty).most_common(8):
        lines.append(f"    {reg}: {count}")
    lines.append("  样例:")
    for path in empty[:6]:
        lines.append(f"    - {os.path.basename(path)}  ({region(path)})")
    lines.append("")

    lines.append("【三、建议优先加强的解析逻辑】")
    lines.append("  1. 上海「××监督抽检信息表合格/不合格.xls」— failed 中占比最高")
    lines.append("  2. 老版 .xls — xlrd 失败后 COM 回退仍失败（加密/损坏/非标准格式）")
    lines.append("  3. PDF 合格/不合格附件 — empty 中约 43%，需 pdfplumber + OCR 表格还原")
    lines.append("  4. 新疆 xls/xlsx — failed 约 383 个，可能有地方特殊表头")
    lines.append("  5. 广西/内蒙古 PDF 专项通报 — empty 中较多扫描件 PDF")
    lines.append("")

    text = "\n".join(lines) + "\n"
    print(text)

    ensure_output_dir()
    out = os.path.join(OUTPUT_DIR, "未解析原因汇总.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
