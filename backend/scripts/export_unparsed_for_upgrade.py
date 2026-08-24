"""复测未解析文件（当前解析器），导出原因汇总与路径清单供加强逻辑。"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir
from scripts.analyze_unparsed_files import diagnose_file

REASON_LABELS = {
    "recovered_now": "当前解析器已可解析（待重扫入库）",
    "planned_skip": "计划抽检清单（已排除）",
    "read_failed_or_empty": "文件无法读取或完全空白",
    "unknown_status": "无法识别合格/不合格",
    "no_header_row": "找不到标准表头",
    "header_not_standard": "有序号但缺少产品名称列",
    "missing_key_columns": "缺少产品/单位关键列",
    "no_data_rows": "有表头无数据行",
    "all_rows_no_company_product": "公司名产品名皆空",
    "rows_filtered": "数据行被过滤",
    "exception": "读取异常",
    "file_missing": "文件不存在",
    "empty_sheet": "空工作表",
    "unknown": "其他",
}
from scripts._report_unparsed import region, tag_empty, tag_failed

REASON_PRIORITY = [
    "recovered_now",
    "exception",
    "read_failed_or_empty",
    "unknown_status",
    "no_header_row",
    "header_not_standard",
    "missing_key_columns",
    "no_data_rows",
    "all_rows_no_company_product",
    "rows_filtered",
    "empty_sheet",
    "file_missing",
    "unknown",
]


def _coarse_tag(path: str, bucket: str) -> str:
    if bucket == "failed":
        return tag_failed(path)
    return tag_empty(path)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()

    with open(CACHE_FILE, encoding="utf-8") as f:
        cached = json.load(f)

    stats = cached.get("stats", {})
    scan = cached.get("scan_info", {})
    failed = scan.get("failed_file_paths", []) or []
    empty = scan.get("empty_file_paths", []) or []

    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for p in failed:
        n = os.path.normcase(p)
        if n not in seen:
            seen.add(n)
            items.append((p, "failed"))
    for p in empty:
        n = os.path.normcase(p)
        if n not in seen:
            seen.add(n)
            items.append((p, "empty"))

    results: list[dict[str, str]] = []
    reason_counter: Counter[str] = Counter()
    coarse_counter: Counter[str] = Counter()
    province_counter: dict[str, Counter[str]] = defaultdict(Counter)
    path_by_reason: dict[str, list[str]] = defaultdict(list)

    total = len(items)
    print(f"复测 {total} 个未解析路径（当前解析器）...", flush=True)

    for i, (path, bucket) in enumerate(items, 1):
        coarse = f"{bucket}:{_coarse_tag(path, bucket)}"
        prov = region(path)
        row = {
            "path": path,
            "basename": os.path.basename(path),
            "bucket": bucket,
            "coarse": coarse,
            "province": prov,
            "reason": "",
            "records": "0",
        }

        if not os.path.isfile(path):
            reason = "file_missing"
        elif bucket == "failed":
            reason = "read_failed_or_empty"
        else:
            try:
                reason = diagnose_file(path, retry_parse=False)
            except Exception:
                reason = "exception"

        label = REASON_LABELS.get(reason, reason)
        row["reason"] = reason
        row["reason_label"] = label
        results.append(row)
        reason_counter[reason] += 1
        coarse_counter[coarse] += 1
        province_counter[prov][reason] += 1
        path_by_reason[reason].append(path)

        if i % 50 == 0 or i == total:
            print(f"  {i}/{total}", flush=True)

    out_dir = Path(ensure_output_dir())
    elapsed = time.time() - t0

    unparsed_ui = stats.get("total_files", 0) - stats.get("parsed_files", 0)
    still = total - reason_counter.get("file_missing", 0)

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("未解析文件复测报告（供加强解析逻辑）")
    lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"缓存扫描时间: {scan.get('scanned_at', '未知')}")
    lines.append(f"复测耗时: {elapsed:.1f}s")
    lines.append("=" * 72)
    lines.append("")
    lines.append("【一、总体】")
    lines.append(f"  界面分母: {stats.get('total_files', 0)}")
    lines.append(f"  已解析: {stats.get('parsed_files', 0)}")
    lines.append(f"  界面未解析: {unparsed_ui}")
    lines.append(f"  本次导出路径: {total}（failed {len(failed)} + empty去重）")
    lines.append(f"  仍无法解析(路径级): {still}")
    lines.append("  注: 未对全量路径重跑 parse_file（PDF OCR 极慢）；细因来自表结构诊断。")
    lines.append("")
    lines.append("【二、细分类原因（当前解析器）】")
    for reason in REASON_PRIORITY:
        if reason not in reason_counter:
            continue
        count = reason_counter[reason]
        label = REASON_LABELS.get(reason, reason)
        pct = count / total * 100 if total else 0
        lines.append(f"  [{count:4d}] ({pct:5.1f}%) {label}  [{reason}]")
    for reason, count in reason_counter.most_common():
        if reason in REASON_PRIORITY:
            continue
        label = REASON_LABELS.get(reason, reason)
        lines.append(f"  [{count:4d}]       {label}  [{reason}]")
    lines.append("")
    lines.append("【三、粗分类（文件类型/版式）】")
    for tag, count in coarse_counter.most_common():
        lines.append(f"  [{count:4d}] {tag}")
    lines.append("")
    lines.append("【四、仍须加强 — 建议优先级】")
    priority_hints = [
        ("empty:xls(表头/版式不识别)", "甘肃/新疆/福建等地表头变体；抽样编号在首列"),
        ("empty:xlsx(表头/版式不识别)", "新疆「_正文.xlsx」及地方统计表"),
        ("empty:PDF附件(打开但抽不出数据行)", "广西/内蒙古扫描件；pdfplumber+OCR"),
        ("failed:上海式监督抽检信息表(.xls)", "新疆等地表名含监督抽检信息"),
        ("failed:老版.xls(非上海命名)", "老版 xls / COM 回退"),
        ("failed:xlsx读取失败", "损坏或特殊 xlsx"),
        ("empty:通告正文副本(_1.xls)", "与主文件去重或跟主表同样解析"),
        ("no_header_row", "无「序号」但有抽样编号+食品名称"),
        ("unknown_status", "汇总页/说明页，考虑排除规则"),
        ("rows_filtered", "有表头有数据但行规则过滤"),
    ]
    for tag, hint in priority_hints:
        c = coarse_counter.get(tag, 0)
        if c:
            lines.append(f"  · {tag} ({c}): {hint}")
    lines.append("")
    lines.append("【五、各省仍无法解析 TOP10】")
    prov_still: Counter[str] = Counter()
    for prov, ctr in province_counter.items():
        prov_still[prov] = sum(
            c for r, c in ctr.items() if r not in ("recovered_now", "file_missing")
        )
    for prov, count in prov_still.most_common(10):
        lines.append(f"  {prov}: {count}")
    lines.append("")
    lines.append("【六、各原因样例路径（每类最多 5 条）】")
    for reason in REASON_PRIORITY:
        paths = path_by_reason.get(reason, [])
        if not paths or reason == "recovered_now":
            continue
        label = REASON_LABELS.get(reason, reason)
        lines.append(f"  >> {label}")
        for p in paths[:5]:
            lines.append(f"     {p}")
    lines.append("")
    lines.append("【七、导出文件】")
    lines.append(f"  {out_dir / '待加强解析规则-汇总.txt'}")
    lines.append(f"  {out_dir / '待加强解析规则-明细.csv'}")
    lines.append(f"  {out_dir / '待加强解析规则-路径索引.txt'}")
    lines.append("  待加强解析规则-路径-<原因>.txt（每个原因一个文件）")

    summary_text = "\n".join(lines) + "\n"
    print("\n" + summary_text)

    (out_dir / "待加强解析规则-汇总.txt").write_text(summary_text, encoding="utf-8")

    with open(out_dir / "待加强解析规则-明细.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "reason",
                "reason_label",
                "bucket",
                "coarse",
                "province",
                "basename",
                "path",
                "records",
            ],
        )
        w.writeheader()
        for row in sorted(results, key=lambda r: (r["reason"], r["province"], r["path"])):
            w.writerow(row)

    index_lines = [
        f"total={total} still={still}",
        "",
    ]
    for reason in REASON_PRIORITY:
        paths = path_by_reason.get(reason, [])
        if not paths:
            continue
        fname = f"待加强解析规则-路径-{reason}.txt"
        (out_dir / fname).write_text("\n".join(paths) + "\n", encoding="utf-8")
        label = REASON_LABELS.get(reason, reason)
        index_lines.append(f"{len(paths):4d}  {label}  ->  {fname}")

    (out_dir / "待加强解析规则-路径索引.txt").write_text(
        "\n".join(index_lines) + "\n", encoding="utf-8"
    )

    for coarse, paths in sorted(
        ((k, [r["path"] for r in results if r["coarse"] == k])
        for k in coarse_counter),
        key=lambda x: -len(x[1]),
    ):
        if not paths:
            continue
        safe = coarse.replace(":", "-").replace("/", "-")
        fname = f"待加强解析规则-粗分-{safe}.txt"
        (out_dir / fname).write_text("\n".join(paths) + "\n", encoding="utf-8")

    print(f"已写入目录: {out_dir}")


if __name__ == "__main__":
    main()
