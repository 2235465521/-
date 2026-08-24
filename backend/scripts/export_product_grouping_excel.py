#!/usr/bin/env python3
"""导出全库产品三层归类表（超级大类/大类/小类），供人工核查；不修改数据库。"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401

from config import OUTPUT_DIR, ensure_output_dir
from food_inspection.db import connection
from food_inspection.product_grouping import (
    build_subclass_merge_map,
    cached_propose_product_group,
    cached_propose_product_subclass,
)
from food_inspection.product_super_category import propose_super_category

from openpyxl import Workbook

THREE_LAYER_HEADERS = [
    "序号",
    "原始产品名",
    "超级大类",
    "校正后超级大类",
    "大类",
    "校正后大类",
    "小类",
    "校正后小类",
    "合格记录数",
    "不合格记录数",
    "合计",
    "小类说明",
    "需人工复核",
]

MAJOR_SUBCLASS_HEADERS = [
    "建议大类",
    "建议小类",
    "原始产品名",
]

INDEX_HEADERS = [
    "建议大类",
    "建议小类",
    "品名数",
    "合格合计",
    "不合格合计",
    "抽检总次数",
    "示例品名",
]

_DETAIL_INDENT = "    "


def _build_subclass_groups(
    detail_rows: list[dict],
    *,
    min_total: int = 1,
) -> list[dict]:
    """按 (建议大类, 建议小类) 分组，供折叠展开校对。"""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in detail_rows:
        if row["total_cnt"] < min_total:
            continue
        key = (row["proposed_major"], row["proposed_subclass"])
        groups[key].append(row)

    group_totals = {
        key: sum(r["total_cnt"] for r in members)
        for key, members in groups.items()
    }

    ordered_keys = sorted(
        groups.keys(),
        key=lambda key: (-group_totals[key], key[0], key[1]),
    )

    result: list[dict] = []
    for major, subclass in ordered_keys:
        members = sorted(
            groups[(major, subclass)],
            key=lambda r: (-r["total_cnt"], r["food_name"]),
        )
        result.append(
            {
                "major": major,
                "subclass": subclass,
                "members": members,
                "member_count": len(members),
                "qualified": sum(r["qualified_cnt"] for r in members),
                "unqualified": sum(r["unqualified_cnt"] for r in members),
                "total": sum(r["total_cnt"] for r in members),
                "examples": [r["food_name"] for r in members[:5]],
            }
        )
    return result


def _write_subclass_index_sheet(ws, groups: list[dict]) -> None:
    """小类索引：一行一个小类，便于逐类定位校对。"""
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill("solid", fgColor="1F4E79")
    font = Font(bold=True, color="FFFFFF")
    for col, title in enumerate(INDEX_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, group in enumerate(groups, 2):
        ws.cell(row=row_idx, column=1, value=group["major"])
        ws.cell(row=row_idx, column=2, value=group["subclass"])
        ws.cell(row=row_idx, column=3, value=group["member_count"])
        ws.cell(row=row_idx, column=4, value=group["qualified"])
        ws.cell(row=row_idx, column=5, value=group["unqualified"])
        ws.cell(row=row_idx, column=6, value=group["total"])
        ws.cell(row=row_idx, column=7, value="；".join(group["examples"]))

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 48
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{max(1, len(groups) + 1)}"


def _write_major_subclass_sheet(ws, groups: list[dict]) -> None:
    """
    大类小类对照：每个小类一行摘要，原始品名默认折叠；
    点击行号左侧 +/- 可展开，品名缩进显示。
    """
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF")
    summary_font = Font(bold=True)
    for col, title in enumerate(MAJOR_SUBCLASS_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    row_idx = 2
    for group in groups:
        count = group["member_count"]
        ws.cell(row=row_idx, column=1, value=group["major"])
        ws.cell(row=row_idx, column=2, value=group["subclass"])
        summary_cell = ws.cell(
            row=row_idx,
            column=3,
            value=f"▶ 共 {count} 个品名（点击左侧 +/- 展开）",
        )
        summary_cell.font = summary_font
        row_idx += 1

        for member in group["members"]:
            name_cell = ws.cell(
                row=row_idx,
                column=3,
                value=f"{_DETAIL_INDENT}{member['food_name']}",
            )
            name_cell.alignment = Alignment(indent=2)
            ws.row_dimensions[row_idx].outline_level = 1
            ws.row_dimensions[row_idx].hidden = True
            row_idx += 1

    ws.sheet_properties.outlinePr.summaryBelow = False
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 42
    ws.freeze_panes = "A2"


THREE_LAYER_SUMMARY_HEADERS = [
    "超级大类",
    "大类",
    "小类",
    "原始品名数",
    "合格合计",
    "不合格合计",
    "总合计",
    "原始品名示例",
]


def _fetch_product_counts() -> list[dict]:
    sql = """
        SELECT food_name,
               SUM(qualified_cnt) AS qualified_cnt,
               SUM(unqualified_cnt) AS unqualified_cnt
        FROM (
            SELECT TRIM(food_name) AS food_name,
                   COUNT(*) AS qualified_cnt,
                   0 AS unqualified_cnt
            FROM inspection_qualified
            WHERE food_name IS NOT NULL AND TRIM(food_name) <> ''
            GROUP BY TRIM(food_name)
            UNION ALL
            SELECT TRIM(food_name) AS food_name,
                   0,
                   COUNT(*)
            FROM inspection_unqualified
            WHERE food_name IS NOT NULL AND TRIM(food_name) <> ''
            GROUP BY TRIM(food_name)
        ) t
        GROUP BY food_name
        ORDER BY (SUM(qualified_cnt) + SUM(unqualified_cnt)) DESC, food_name
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [
        {
            "food_name": row["food_name"],
            "qualified_cnt": int(row["qualified_cnt"] or 0),
            "unqualified_cnt": int(row["unqualified_cnt"] or 0),
        }
        for row in rows
    ]


def _build_rows(raw_rows: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    subclass_groups: dict[str, list[dict]] = defaultdict(list)
    detail_rows: list[dict] = []

    for row in raw_rows:
        major, _, _ = cached_propose_product_group(row["food_name"])
        subclass, subclass_note, subclass_review = cached_propose_product_subclass(row["food_name"])
        major_name = major or row["food_name"]
        subclass_name = subclass or row["food_name"]
        super_cat, _ = propose_super_category(subclass_name, major_name, row["food_name"])
        enriched = {
            **row,
            "proposed_super": super_cat,
            "proposed_major": major_name,
            "proposed_subclass": subclass_name,
            "subclass_note": subclass_note,
            "needs_review": subclass_review,
            "total_cnt": row["qualified_cnt"] + row["unqualified_cnt"],
        }
        subclass_groups[subclass_name].append(enriched)
        detail_rows.append(enriched)

    merge_map = build_subclass_merge_map(subclass_groups)
    print(f"  单样品小类向上合并：{len(merge_map):,} 组", flush=True)

    merged_subclass_groups: dict[str, list[dict]] = defaultdict(list)
    for row in detail_rows:
        sub = row["proposed_subclass"]
        if sub in merge_map:
            merged, note = merge_map[sub]
            row["proposed_subclass"] = merged
            row["subclass_note"] = (
                f"{row['subclass_note']}；{note}" if row["subclass_note"] else note
            )
        row["proposed_super"], _ = propose_super_category(
            row["proposed_subclass"],
            row["proposed_major"],
            row["food_name"],
        )
        merged_subclass_groups[row["proposed_subclass"]].append(row)

    return detail_rows, dict(merged_subclass_groups)


def export_excel(output_path: Path, *, min_total: int = 1) -> Path:
    print("正在从数据库读取产品名统计…", flush=True)
    raw_rows = _fetch_product_counts()
    print(f"  共 {len(raw_rows):,} 个不同产品名", flush=True)

    detail_rows, _subclass_groups = _build_rows(raw_rows)

    super_set = {r["proposed_super"] for r in detail_rows}
    print(f"  超级大类 {len(super_set)} 种", flush=True)

    detail_rows.sort(
        key=lambda r: (
            r["proposed_super"],
            r["proposed_major"],
            r["proposed_subclass"],
            -r["total_cnt"],
            r["food_name"],
        )
    )

    triple_meta: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {
            "member_count": 0,
            "examples": [],
            "qualified": 0,
            "unqualified": 0,
            "total": 0,
        }
    )
    for row in detail_rows:
        if row["total_cnt"] < min_total:
            continue
        key = (row["proposed_super"], row["proposed_major"], row["proposed_subclass"])
        meta = triple_meta[key]
        meta["member_count"] += 1
        meta["qualified"] += row["qualified_cnt"]
        meta["unqualified"] += row["unqualified_cnt"]
        meta["total"] += row["total_cnt"]
        if len(meta["examples"]) < 8:
            meta["examples"].append(row["food_name"])

    ensure_output_dir()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"正在写入 Excel（三层明细 {len(detail_rows):,} 行）…", flush=True)
    wb = Workbook(write_only=True)

    info = wb.create_sheet("使用说明")
    info.append(["食品安全抽检 · 产品三层归类表"])
    info.append([f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
    info.append([])
    info.append(["层级：超级大类 → 大类 → 小类 → 原始产品名"])
    info.append(["超级大类示例：水果类、蔬菜类、干果类、肉制品、奶制品、粮油类、饮料类…"])
    info.append(["工作表："])
    info.append(
        [
            "大类小类对照",
            "「小类索引」逐类浏览；「大类小类对照」默认折叠品名，点 +/- 展开",
        ]
    )
    info.append(["三层归类表", "全部原始品名明细"])
    info.append(["三层汇总", "超级大类+大类+小类统计"])

    subclass_groups = _build_subclass_groups(detail_rows, min_total=min_total)
    detail_line_count = sum(g["member_count"] for g in subclass_groups)
    print(
        f"  大类小类对照：{len(subclass_groups):,} 个小类，"
        f"{detail_line_count:,} 条品名（默认折叠）",
        flush=True,
    )

    summary = wb.create_sheet("三层汇总")
    summary.append(THREE_LAYER_SUMMARY_HEADERS)
    summary_rows = sorted(
        triple_meta.items(),
        key=lambda x: (x[0][0], x[0][1], -x[1]["total"], x[0][2]),
    )
    for (super_cat, major, subclass), meta in summary_rows:
        summary.append(
            [
                super_cat,
                major,
                subclass,
                meta["member_count"],
                meta["qualified"],
                meta["unqualified"],
                meta["total"],
                "、".join(meta["examples"][:8]),
            ]
        )

    detail = wb.create_sheet("三层归类表")
    detail.append(THREE_LAYER_HEADERS)
    for idx, row in enumerate(detail_rows, 1):
        if row["total_cnt"] < min_total:
            continue
        detail.append(
            [
                idx,
                row["food_name"],
                row["proposed_super"],
                "",
                row["proposed_major"],
                "",
                row["proposed_subclass"],
                "",
                row["qualified_cnt"],
                row["unqualified_cnt"],
                row["total_cnt"],
                row["subclass_note"],
                "是" if row["needs_review"] else "",
            ]
        )
        if idx % 50000 == 0:
            print(f"  已写入 {idx:,} 行…", flush=True)

    wb.save(output_path)

    # 大类小类对照表（含合并单元格，单独写入同目录）
    from openpyxl import Workbook as StdWorkbook

    major_path = output_path.with_name("大类小类对照表.xlsx")
    mwb = StdWorkbook()
    index_ws = mwb.active
    index_ws.title = "小类索引"
    _write_subclass_index_sheet(index_ws, subclass_groups)
    detail_ws = mwb.create_sheet("大类小类对照")
    _write_major_subclass_sheet(detail_ws, subclass_groups)
    mwb.save(major_path)

    print(f"已导出：{output_path}", flush=True)
    print(f"  大类小类对照：{major_path}", flush=True)
    print(f"  三层汇总：{len(summary_rows):,} 行", flush=True)
    return output_path


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="导出产品三层归类 Excel（不写库）")
    parser.add_argument(
        "--output",
        default=str(Path(OUTPUT_DIR) / "产品三层归类表.xlsx"),
        help="输出 Excel 路径",
    )
    parser.add_argument("--min-total", type=int, default=1)
    args = parser.parse_args()
    export_excel(Path(args.output), min_total=max(args.min_total, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
