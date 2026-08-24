#!/usr/bin/env python3
"""导入东莞市「风险控制 / 核查处置」叙述型 PDF（不合格产品正文）。"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.db import connection  # noqa: E402
from food_inspection.mysql_v2 import create_compat_view, insert_records_batch  # noqa: E402
from food_inspection.parser import (  # noqa: E402
    iter_excel_files,
    parse_file,
)
from food_inspection.parser.category_fill import (  # noqa: E402
    backfill_record_category,
    build_category_map,
    merge_category_maps,
)
from food_inspection.parser.fields import source_relative_key  # noqa: E402
from food_inspection.parser.models import Record  # noqa: E402

_BATCH_SIZE = 200


def _is_target_pdf(filepath: str) -> bool:
    name = os.path.basename(filepath)
    if not name.lower().endswith(".pdf"):
        return False
    if "/东莞市/" not in filepath.replace("\\", "/"):
        return False
    return "风险控制" in name or "核查处置" in name


def _load_imported_keys() -> set[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT file_source FROM inspection_base")
        return {str(row["file_source"] or "").casefold() for row in cur.fetchall()}


def _parse_worker(filepath: str) -> tuple[str, list[Record] | None, str]:
    try:
        return filepath, parse_file(filepath), ""
    except Exception as exc:
        return filepath, None, str(exc)


def main() -> int:
    imported_keys = _load_imported_keys()
    files = [
        fp
        for fp in iter_excel_files()
        if _is_target_pdf(fp)
        and source_relative_key(fp).casefold() not in imported_keys
    ]
    files.sort()
    print(f"东莞叙述型 PDF 待导入: {len(files)} 个", flush=True)

    workers = max(int(os.environ.get("IMPORT_WORKERS", "2")), 1)
    imported = 0
    parsed_files = 0
    skipped_empty = 0
    failed: list[str] = []
    global_category_map: dict[str, str] = {}
    started = time.time()

    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
        next_id = int(cur.fetchone()["n"])
        pending: list[tuple[Record, int]] = []

        def flush() -> None:
            nonlocal pending
            if pending:
                insert_records_batch(cur, pending)
                pending = []

        if workers > 1 and len(files) > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_parse_worker, fp): fp for fp in files}
                for i, future in enumerate(as_completed(futures), 1):
                    filepath, records, err = future.result()
                    if err:
                        failed.append(f"{filepath}\t{err}")
                        continue
                    if not records:
                        skipped_empty += 1
                        continue
                    global_category_map = merge_category_maps(
                        global_category_map, build_category_map(records)
                    )
                    rel_key = source_relative_key(filepath)
                    if rel_key:
                        imported_keys.add(rel_key)
                    for record in records:
                        backfill_record_category(record, global_category_map)
                        pending.append((record, next_id))
                        next_id += 1
                        imported += 1
                    parsed_files += 1
                    if len(pending) >= _BATCH_SIZE:
                        flush()
                    if i % 10 == 0:
                        print(
                            f"进度 {i}/{len(files)}：已入库 {imported} 条，"
                            f"成功文件 {parsed_files}，空 {skipped_empty}",
                            flush=True,
                        )
        else:
            for i, filepath in enumerate(files, 1):
                filepath, records, err = _parse_worker(filepath)
                if err:
                    failed.append(f"{filepath}\t{err}")
                    continue
                if not records:
                    skipped_empty += 1
                    continue
                global_category_map = merge_category_maps(
                    global_category_map, build_category_map(records)
                )
                rel_key = source_relative_key(filepath)
                if rel_key:
                    imported_keys.add(rel_key)
                for record in records:
                    backfill_record_category(record, global_category_map)
                    pending.append((record, next_id))
                    next_id += 1
                    imported += 1
                parsed_files += 1
                if len(pending) >= _BATCH_SIZE:
                    flush()
                if i % 10 == 0:
                    print(
                        f"进度 {i}/{len(files)}：已入库 {imported} 条，"
                        f"成功文件 {parsed_files}，空 {skipped_empty}",
                        flush=True,
                    )

        flush()
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
        cur.execute(f"ALTER TABLE inspection_base AUTO_INCREMENT = {int(cur.fetchone()['n'])}")

    create_compat_view()
    elapsed = time.time() - started
    print(
        f"完成：入库 {imported} 条，成功文件 {parsed_files} 个，"
        f"解析为空 {skipped_empty} 个，失败 {len(failed)} 个，"
        f"耗时 {elapsed / 60:.1f} 分钟",
        flush=True,
    )
    if failed:
        fail_log = BACKEND_DIR / "output" / "dongguan_narrative_import_errors.log"
        fail_log.write_text("\n".join(failed), encoding="utf-8")
        print(f"失败列表: {fail_log}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
