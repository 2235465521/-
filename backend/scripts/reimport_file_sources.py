#!/usr/bin/env python3
"""按 file_source 删除并重新解析入库（修正结论列误判等历史数据）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT  # noqa: E402
from food_inspection.db import connection  # noqa: E402
from food_inspection.mysql_v2 import create_compat_view, insert_records_batch  # noqa: E402
from food_inspection.parser import iter_excel_files, parse_file  # noqa: E402
from food_inspection.parser.fields import source_relative_key  # noqa: E402

_BATCH = 500


def _is_disposal_source(rel: str) -> bool:
    name = os.path.basename(rel.replace("\\", "/"))
    return ("核查处置" in rel or "风险控制" in rel) and (
        "_正文" in name or name.endswith("_正文.xlsx")
    )


def _match_file(path: str, *, city: str, pattern: str, disposal_only: bool) -> bool:
    rel = source_relative_key(path) or path.replace("\\", "/")
    if disposal_only:
        return _is_disposal_source(rel) and os.path.isfile(path)
    if city and f"/{city.strip()}/" not in rel and not rel.startswith(f"{city.strip()}/"):
        return False
    if pattern and pattern not in rel:
        return False
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="删除并重新导入匹配的源文件")
    parser.add_argument("--city", default="", help="路径中含该城市，如 韶关市")
    parser.add_argument("--pattern", default="食品监督抽检产品信息", help="file_source 须包含的子串")
    parser.add_argument("--disposal", action="store_true", help="仅核查处置/风险控制 _正文 文件")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files = [
        fp
        for fp in iter_excel_files()
        if _match_file(
            fp,
            city=args.city,
            pattern=args.pattern if not args.disposal else "",
            disposal_only=args.disposal,
        )
    ]
    if not files:
        print("未找到匹配的源文件")
        return 0

    rel_keys = sorted({source_relative_key(fp) for fp in files if source_relative_key(fp)})
    print(f"匹配源文件 {len(files)} 个，相对路径 {len(rel_keys)} 个")

    deleted = 0
    imported = 0
    qualified = 0
    unqualified = 0

    with connection() as conn, conn.cursor() as cur:
        if not args.dry_run:
            for rel in rel_keys:
                cur.execute("DELETE FROM inspection_base WHERE file_source = %s", (rel,))
                deleted += cur.rowcount

            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
            next_id = int(cur.fetchone()["n"])
        else:
            cur.execute(
                "SELECT COUNT(*) AS n FROM inspection_base WHERE file_source IN %s",
                (tuple(rel_keys),),
            )
            deleted = int(cur.fetchone()["n"])
            next_id = 0

        pending: list = []
        for fp in files:
            records = parse_file(fp)
            for record in records:
                if args.dry_run:
                    imported += 1
                    if record.status == "qualified":
                        qualified += 1
                    else:
                        unqualified += 1
                    continue
                pending.append((record, next_id))
                next_id += 1
                imported += 1
                if record.status == "qualified":
                    qualified += 1
                else:
                    unqualified += 1
                if len(pending) >= _BATCH:
                    insert_records_batch(cur, pending)
                    pending.clear()

        if not args.dry_run and pending:
            insert_records_batch(cur, pending)
            conn.commit()
            create_compat_view()

    print(f"删除旧记录: {deleted}")
    print(f"重新导入: {imported}（合格 {qualified}，不合格 {unqualified}）")
    if args.dry_run:
        print("（dry-run，未写入数据库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
