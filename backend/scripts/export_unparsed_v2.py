#!/usr/bin/env python3
"""导出 v2 五表库中尚未入库的源文件，附解析诊断供增强规则。"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT, OUTPUT_DIR  # noqa: E402
from food_inspection.db import connection  # noqa: E402
from food_inspection.parser import (  # noqa: E402
    is_non_inspection_detail_file,
    is_planned_sampling_file,
    iter_excel_files,
    parse_file,
)
from food_inspection.parser.disposal_narrative import (  # noqa: E402
    _is_captcha_shell,
    _is_disposal_narrative_file,
    _is_nav_shell_only,
    _is_narrative_text,
    extract_disposal_narrative_text,
    is_skippable_disposal_zhengwen,
)
from food_inspection.parser.fields import source_relative_key  # noqa: E402
from scripts.analyze_unparsed_files import diagnose_sheets  # noqa: E402

REASON_LABELS = {
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
    "empty_sheet": "空工作表",
    "unknown": "其他",
}

_REASON_ZHENGWEN = {
    "nav_shell": "正文壳-仅网站导航无抽检正文",
    "captcha_shell": "正文壳-网站人机验证页(非抽检正文)",
    "plan_meta": "正文壳-抽检计划/意见反馈类",
    "structured_skip": "结构化核查处置正文-跳过（食品名称/进购日期字段体）",
    "disposal_has_text": "核查处置正文-有内容但未匹配规则",
    "disposal_empty": "核查处置正文-无有效正文",
    "disposal_not": "正文xlsx-非核查处置类",
}


def _load_imported_keys(province: str | None) -> set[str]:
    with connection() as conn, conn.cursor() as cur:
        if province:
            cur.execute(
                "SELECT DISTINCT file_source FROM inspection_base WHERE province=%s",
                (province,),
            )
        else:
            cur.execute("SELECT DISTINCT file_source FROM inspection_base")
        return {str(row["file_source"] or "").casefold() for row in cur.fetchall()}


def _path_parts(rel: str) -> tuple[str, str, str]:
    parts = rel.replace("\\", "/").strip("/").split("/")
    province = parts[0] if len(parts) > 0 else ""
    city = parts[1] if len(parts) > 1 else ""
    year = parts[2] if len(parts) > 2 and re.fullmatch(r"20\d{2}", parts[2]) else ""
    return province, city, year


def _diagnose_zhengwen(filepath: str) -> tuple[str, str]:
    name = os.path.basename(filepath)
    if not name.endswith("_正文.xlsx"):
        return "", ""
    if is_planned_sampling_file(filepath):
        return "plan_meta", _REASON_ZHENGWEN["plan_meta"]
    if not _is_disposal_narrative_file(filepath):
        return "disposal_not", _REASON_ZHENGWEN["disposal_not"]
    text = extract_disposal_narrative_text(filepath)
    if is_skippable_disposal_zhengwen(filepath, text):
        return "structured_skip", _REASON_ZHENGWEN["structured_skip"]
    if _is_captcha_shell(text):
        return "captcha_shell", _REASON_ZHENGWEN["captcha_shell"]
    if _is_nav_shell_only(text):
        return "nav_shell", _REASON_ZHENGWEN["nav_shell"]
    compact = re.sub(r"\s+", "", text)
    if _is_narrative_text(text) or "购进" in compact or "销售" in compact:
        return "disposal_has_text", _REASON_ZHENGWEN["disposal_has_text"]
    if len(compact) < 120:
        return "disposal_empty", _REASON_ZHENGWEN["disposal_empty"]
    return "disposal_has_text", _REASON_ZHENGWEN["disposal_has_text"]


def _text_preview(filepath: str, limit: int = 240) -> str:
    if not filepath.endswith("_正文.xlsx"):
        return ""
    text = extract_disposal_narrative_text(filepath)
    compact = re.sub(r"\s+", " ", text).strip()
    for marker in ("抽检基本情况", "通告如下", "公告如下", "一、"):
        if marker in compact:
            pos = compact.find(marker)
            compact = compact[max(0, pos - 20) : pos + limit]
            break
    return compact[:limit]


def _diagnose(filepath: str) -> tuple[str, str, int]:
    if is_planned_sampling_file(filepath):
        return "planned_skip", REASON_LABELS.get("planned_skip", "计划抽检"), 0
    if is_non_inspection_detail_file(filepath):
        return "non_detail_skip", "非抽检明细附件", 0

    zw_code, zw_label = _diagnose_zhengwen(filepath)
    if zw_code:
        try:
            records = parse_file(filepath)
            if records:
                return "recovered_now", "当前解析器已可解析", len(records)
        except Exception:
            return "exception", REASON_LABELS.get("exception", "读取异常"), 0
        return zw_code, zw_label, 0

    try:
        records = parse_file(filepath)
        if records:
            return "recovered_now", "当前解析器已可解析（待入库）", len(records)
    except Exception:
        return "exception", REASON_LABELS.get("exception", "读取异常"), 0

    sheet_reason = diagnose_sheets(filepath)
    return sheet_reason, REASON_LABELS.get(sheet_reason, sheet_reason), 0


def export_unparsed(*, province: str | None, out_csv: Path) -> int:
    imported = _load_imported_keys(province)
    files = list(iter_excel_files())
    if province:
        prefix = f"{province.strip()}/".casefold()
        files = [
            fp
            for fp in files
            if source_relative_key(fp).casefold().startswith(prefix)
            or f"/{province.strip()}/" in fp.replace("\\", "/")
        ]

    rows: list[dict[str, str]] = []
    reason_counter: Counter[str] = Counter()

    for fp in files:
        rel = source_relative_key(fp)
        rel_key = rel.casefold()
        in_db = rel_key in imported
        prov, city, year = _path_parts(rel)
        name = os.path.basename(fp)
        ext = os.path.splitext(name)[1].lower()

        reason_code, reason_label, parse_count = _diagnose(fp)
        if in_db:
            continue
        if reason_code in ("planned_skip", "non_detail_skip", "structured_skip"):
            continue
        if reason_code == "recovered_now":
            continue

        reason_counter[reason_label] += 1
        rows.append(
            {
                "province": prov,
                "city": city,
                "year": year,
                "relative_path": rel,
                "filename": name,
                "ext": ext.lstrip("."),
                "is_zhengwen": "1" if name.endswith("_正文.xlsx") else "0",
                "is_disposal": "1" if _is_disposal_narrative_file(fp) else "0",
                "reason_code": reason_code,
                "reason": reason_label,
                "text_preview": _text_preview(fp),
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "province", "city", "year", "relative_path", "filename", "ext",
        "is_zhengwen", "is_disposal", "reason_code", "reason", "text_preview",
    ]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary_path = out_csv.with_suffix(".summary.txt")
    lines = [
        f"数据根目录: {DATA_ROOT}",
        f"省份筛选: {province or '全部'}",
        f"源文件总数: {len(files)}",
        f"已入库文件: {len(imported)}",
        f"未解析导出: {len(rows)}",
        "",
        "【按原因统计】",
    ]
    for label, count in reason_counter.most_common():
        lines.append(f"  {count:5d}  {label}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"CSV: {out_csv}")
    print(f"汇总: {summary_path}")
    print(f"未解析文件: {len(rows)}")
    for label, count in reason_counter.most_common(8):
        print(f"  {count:5d}  {label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 v2 未入库源文件清单")
    parser.add_argument("--province", default="浙江省", help="省份目录，默认浙江省")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出 CSV 路径",
    )
    args = parser.parse_args()
    prov = (args.province or "").strip() or None
    out = args.out
    if out is None:
        tag = prov or "全国"
        out = Path(OUTPUT_DIR) / f"未解析文件汇总-{tag}.csv"
    return export_unparsed(province=prov, out_csv=out)


if __name__ == "__main__":
    raise SystemExit(main())
