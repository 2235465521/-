"""导出公司名异常样例的源文件路径。"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data_cache.json"
OUT = ROOT / "output" / "公司名异常样例路径.txt"


def dump_group(
    lines: list[str],
    title: str,
    predicate,
    records: list[dict],
    max_files: int = 10,
) -> None:
    lines.append("=" * 72)
    lines.append(title)
    lines.append("=" * 72)
    by_file: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        company = record.get("company") or ""
        if predicate(company, record):
            by_file[record.get("source_file") or ""].append(record)

    total = sum(len(v) for v in by_file.values())
    lines.append(f"总记录数: {total}")
    lines.append(f"涉及文件数: {len(by_file)}")
    lines.append("")

    for i, (filepath, recs) in enumerate(
        sorted(by_file.items(), key=lambda x: -len(x[1]))[:max_files], 1
    ):
        sample = recs[0]
        lines.append(f"[{i}] 本文件 {len(recs)} 条")
        lines.append(filepath)
        lines.append(f"    公司字段: {(sample.get('company') or '')[:150]}")
        lines.append(f"    产品: {sample.get('product') or ''}")
        lines.append(
            f"    省市: {sample.get('source_province') or ''} / {sample.get('source_city') or ''}"
        )
        lines.append(f"    工作表: {sample.get('source_sheet') or ''}")
        lines.append("")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE, encoding="utf-8") as f:
        data = json.load(f)

    unqualified = data.get("unqualified", [])
    lines: list[str] = [
        "公司名异常样例 - 源文件路径清单",
        f"数据缓存: {CACHE}",
        "",
    ]

    dump_group(
        lines,
        "【第1名】委托方/受托方合并写法 - 红牛（榜单 32 次）",
        lambda c, _r: "委托方" in c and "红牛" in c,
        unqualified,
    )
    dump_group(
        lines,
        "【第3名】委托方/受托方合并写法 - 东鹏（榜单 24 次）",
        lambda c, _r: "委托方" in c and "东鹏" in c,
        unqualified,
    )
    dump_group(
        lines,
        "【扩展】全部委托方/受托方合并写法（各取前 10 个文件）",
        lambda c, _r: "委托方" in c and "受托方" in c,
        unqualified,
        max_files=10,
    )
    dump_group(
        lines,
        "【第6名】表头误入「生产企业名称」（榜单 14 次）",
        lambda c, _r: c in ("生产企业名称", "标称生产企业名称"),
        unqualified,
    )

    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"已写入: {OUT}")


if __name__ == "__main__":
    main()
