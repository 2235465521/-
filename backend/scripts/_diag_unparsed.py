"""Diagnose why sample unparsed files fail."""
from __future__ import annotations

import os
import sys
import traceback

import scripts._bootstrap  # noqa: F401

from food_inspection.parser import parse_file
from food_inspection.parser.classification import (
    _detect_file_mode,
    _detect_sheet_status,
    _infer_status_from_context,
)
from food_inspection.parser.io import _read_all_sheets
from food_inspection.parser.layout import _find_header_row, _resolve_sheet_layout
from food_inspection.parser.text import _clean


def diag(path: str) -> None:
    print("=" * 80)
    print(os.path.basename(path))
    print(path)
    if not os.path.isfile(path):
        print("  MISSING")
        return
    try:
        recs = parse_file(path)
        print(f"  parse_file -> {len(recs)} records")
        if recs:
            return
    except Exception as e:
        print(f"  parse_file EXCEPTION: {e}")
        traceback.print_exc()

    try:
        sheets = _read_all_sheets(path)
        print(f"  sheets: {len(sheets)}")
        for sn, rows, st in sheets[:2]:
            print(f"  sheet={sn!r} rows={len(rows)} text_len={len(st)}")
            if not rows:
                continue
            for i, row in enumerate(rows[:6]):
                cells = [_clean(c) for c in row[:12]]
                print(f"    r{i}: {cells}")
            mode = _detect_file_mode(os.path.basename(path))
            status = _detect_sheet_status(sn, st, mode, rows)
            if status is None:
                status = _infer_status_from_context(path, st, rows)
            print(f"  file_mode={mode} status={status}")
            hdr = _find_header_row(rows)
            print(f"  header_row={hdr}")
            layout = _resolve_sheet_layout(rows)
            if layout:
                hi, headers, col_map, lm = layout
                print(f"  layout={lm} header_idx={hi} col_map={col_map}")
                if headers:
                    print(f"  headers={headers[:15]}")
            else:
                print("  layout=None")
    except Exception as e:
        print(f"  read EXCEPTION: {e}")
        traceback.print_exc()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    samples = [
        r"Z:\全国各省市食品安全监督抽查\新疆维吾尔自治区\阿勒泰地区\青河县\2025\关于公布2025年第三期学校食堂食品安全监督抽检信息的公告\关于公布2025年第三期学校食堂食品安全监督抽检信息统计表.xls",
        r"Z:\全国各省市食品安全监督抽查\安徽省\宣城市\2024\宣城市市场监督管理局食品安全抽检信息通告（2024年第17期）\7.食糖监督抽检产品合格信息.xls",
        r"Z:\全国各省市食品安全监督抽查\甘肃\兰州\2025\兰州市市场监督管理局2024年10月食品抽检信息通告 兰市场监通告〔2024〕9号\downfile.jsp_classid=0&filename=34b82e87cb6e4c8683a6e0eb38f512f1.xls",
        r"Z:\全国各省市食品安全监督抽查\吉林省\吉林市\2025\关于春节期间食品专项抽检（你点我检）情况的通告（2025年第1期）\附件3：食品抽检不合格（春节专项）.pdf",
        r"Z:\全国各省市食品安全监督抽查\广西壮族自治区\南宁市\2024\南宁市市场监督管理局食品安全抽检信息通告（2024年28期）\附件2 食品安全监督抽检不合格产品信息（第28期）.pdf",
    ]
    if len(sys.argv) > 1:
        samples = sys.argv[1:]
    for p in samples:
        diag(p)


if __name__ == "__main__":
    main()
