import scripts._bootstrap  # noqa: F401
from config import CACHE_FILE, OUTPUT_DIR, ensure_output_dir
# -*- coding: utf-8 -*-
"""快速写出未入库文件完整路径清单。"""
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

from food_inspection.parser import is_non_inspection_detail_file, is_planned_sampling_file, iter_excel_files
from food_inspection.scan import collect_indexed_paths, normalize_path

CACHE = CACHE_FILE

with open(CACHE, encoding="utf-8") as f:
    cached = json.load(f)
parsed, _ = collect_indexed_paths(cached)
left = []
for f in iter_excel_files():
    if is_planned_sampling_file(f):
        continue
    if normalize_path(f) not in parsed:
        left.append(f)


def bucket(p: str) -> str:
    name = os.path.basename(p).replace(" ", "")
    ext = os.path.splitext(p)[1].lower()
    if is_non_inspection_detail_file(p):
        return "00_建议排除_非明细附件"
    if ext == ".pdf":
        if "合格表" in name or "不合格表" in name:
            return "02_PDF_福建扫描合格不合格表_OCR"
        if "合格产品" in name or "不合格产品" in name:
            return "02_PDF_广西等产品信息表_OCR"
        return "02_PDF_其他"
    if name.startswith("Cp") or name.startswith("Cq"):
        return "03_Excel_宿州等乱码文件名"
    if "downfile.jsp" in name or ".xls.xls" in name:
        return "03_Excel_下载页或双扩展名"
    if len(os.path.basename(p)) < 32 and "合格信息" not in name and "不合格" not in name:
        return "03_Excel_表头前有分类标题行"
    return "03_Excel_其他"


groups: dict[str, list[str]] = defaultdict(list)
for p in left:
    groups[bucket(p)].append(p)

need = sum(len(v) for k, v in groups.items() if not k.startswith("00"))

summary = [
    "待升级解析规则 — 汇总",
    "=" * 72,
    f"未入库文件: {len(left)}",
    f"需您提供解析规则: {need}",
    f"建议排除(非明细): {len(groups['00_建议排除_非明细附件'])}",
    "",
    "【分组统计】",
]
for k in sorted(groups):
    summary.append(f"  {k}: {len(groups[k])}")

summary.extend(
    [
        "",
        "【建议您优先给规则的类别】",
        "  A. 03_Excel_宿州等乱码文件名 — 表头在第二行，第一行是分类标题",
        "  B. 03_Excel_表头前有分类标题行 — 安徽宣城/淮北等 .xls",
        "  C. 03_Excel_甘肃兰州 — 普通食品合格/不合格 xls，表头标准",
        "  D. 02_PDF_广西等产品信息表 — 扫描件，列名常换行(样品名/称)",
        "  E. 02_PDF_福建扫描合格不合格表 — 多页纯图片 PDF",
        "",
        "【您提供规则时可写】",
        "  - 样例文件路径 + 表头列名一行 + 合格/不合格判定方式",
        "  - 或发一张表头截图",
        "",
        "完整路径: 待升级解析规则-路径清单.txt",
    ]
)

ensure_output_dir()
with open(os.path.join(OUTPUT_DIR, "待升级解析规则-汇总.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(summary) + "\n")

path_lines = ["待升级解析规则 — 完整路径", "=" * 72, f"共 {len(left)} 个", ""]
for k in sorted(groups):
    path_lines.append("")
    path_lines.append(f"## {k} ({len(groups[k])})")
    path_lines.append("-" * 72)
    path_lines.extend(groups[k])

with open(os.path.join(OUTPUT_DIR, "待升级解析规则-路径清单.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(path_lines) + "\n")

print("OK", len(left), "need", need)
for k in sorted(groups):
    print(k, len(groups[k]))
