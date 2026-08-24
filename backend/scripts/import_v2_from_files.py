#!/usr/bin/env python3
"""从 Z 盘（DATA_ROOT）源文件解析并写入五表结构。默认先导入 1000 行供校验。"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT, OUTPUT_DIR  # noqa: E402
from food_inspection.db import connection  # noqa: E402
from food_inspection.mysql_v2 import (  # noqa: E402
    create_compat_view,
    init_schema,
    insert_records_batch,
    record_to_rows,
)
from food_inspection.pipeline.guard import parse_file_guarded
from food_inspection.parser.fields import source_relative_key, _normalize_province  # noqa: E402
from food_inspection.parser.category_fill import (  # noqa: E402
    backfill_record_category,
    build_category_map,
    merge_category_maps,
)
from food_inspection.parser.models import Record  # noqa: E402

_BATCH_SIZE = 500
_PROGRESS_EVERY = 5000


def _file_parse_priority(filepath: str) -> tuple[int, str]:
    """Excel 优先，PDF 靠后（PDF 含 OCR 较慢）。"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return (2, filepath)
    return (0, filepath)


def _parse_file_worker(filepath: str) -> tuple[str, list[Record] | None, str]:
    if is_planned_sampling_file(filepath) or is_non_inspection_detail_file(filepath):
        return filepath, None, ""
    try:
        records, err, _ = parse_file_guarded(filepath)
        if err:
            return filepath, None, err
        return filepath, records, ""
    except Exception as exc:
        return filepath, None, str(exc)


def _ingest_parsed_file(
    filepath: str,
    records: list[Record],
    *,
    imported_keys: set[str],
    skip_imported: bool,
    status_filter: str | None,
    unlimited: bool,
    limit: int | None,
    imported: int,
    next_id: int,
    global_category_map: dict[str, str],
    pending_batch: list[tuple[Record, int]],
    review_csv: Path | None,
    review_rows: list[dict[str, str]],
) -> tuple[int, int, int, dict[str, str], list[tuple[Record, int]]]:
    parsed_files = 1
    if skip_imported:
        rel_key = source_relative_key(filepath)
        if rel_key:
            imported_keys.add(rel_key)
    global_category_map = merge_category_maps(
        global_category_map,
        build_category_map(records),
    )
    for record in records:
        backfill_record_category(record, global_category_map)
        if status_filter and record.status != status_filter:
            continue
        if not unlimited and imported >= (limit or 0):
            break
        pending_batch.append((record, next_id))
        if review_csv is not None:
            review_rows.append(_review_row(record, next_id))
        next_id += 1
        imported += 1
    return imported, next_id, parsed_files, global_category_map, pending_batch


def _review_row(record: Record, base_id: int) -> dict[str, str]:
    rows = record_to_rows(record, base_id)
    base = rows["base"]
    company = rows["company"]
    address = rows["address"]
    row = {
        "id": str(base_id),
        "province": base[1],
        "city": base[2],
        "year": base[3],
        "status": base[4],
        "batch_serial": base[5],
        "file_source": base[6],
        "source_sheet": base[7],
        "sampled_company": company[1],
        "manufacturer": company[2],
        "address": address[1] or "",
        "region": address[2],
        "food_name": "",
        "category": "",
        "unqualified_item": "",
        "test_result": "",
        "standard_value": "",
        "reason_raw": (record.reason or "")[:300],
    }
    if "qualified" in rows:
        row["food_name"] = rows["qualified"][1]
        row["category"] = rows["qualified"][2]
    else:
        u = rows["unqualified"]
        row["food_name"] = u[1]
        row["category"] = u[2]
        row["unqualified_item"] = u[3]
        row["test_result"] = u[4]
        row["standard_value"] = u[5]
    return row


def _load_imported_file_keys() -> set[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT file_source FROM inspection_base")
        return {str(row["file_source"] or "").casefold() for row in cur.fetchall()}


def import_from_files(
    *,
    limit: int | None,
    reset: bool,
    review_csv: Path | None,
    status_filter: str | None = None,
    skip_imported: bool = False,
    workers: int = 1,
    province: str | None = None,
    only_ext: str | None = None,
) -> int:
    if not Path(DATA_ROOT).is_dir():
        print(f"数据目录不存在: {DATA_ROOT}", file=sys.stderr)
        return 1

    unlimited = limit is None
    print(f"数据根目录: {DATA_ROOT}")
    if status_filter:
        print(f"仅导入: {status_filter}")
    if reset:
        print("重建五表结构（清空旧数据）…")
        init_schema(with_view=False)

    files = list(iter_excel_files())
    if province:
        province_dir = _normalize_province(province.strip())
        prefix = f"{province_dir}/".casefold()
        files = [
            fp
            for fp in files
            if source_relative_key(fp).startswith(prefix)
            or f"/{province_dir}/" in fp.replace("\\", "/")
        ]
        print(f"省份筛选: {province_dir}，源文件 {len(files)} 个")
    if only_ext:
        ext = only_ext.lower().lstrip(".")
        files = [
            fp
            for fp in files
            if os.path.splitext(fp)[1].lower().lstrip(".") == ext
            or (ext == "xlsx" and fp.lower().endswith(".xls"))
        ]
        print(f"仅导入 .{ext} 文件，剩余 {len(files)} 个")
    if status_filter == "unqualified":
        def _prio(path: str) -> tuple[int, str]:
            name = path.replace("\\", "/")
            if "不合格" in name or "不 合 格" in name:
                return (0, name)
            if "合格" in name and "不合格" not in name:
                return (2, name)
            return (1, name)

        files.sort(key=_prio)

    if skip_imported:
        files.sort(key=_file_parse_priority)

    label = {"qualified": "合格", "unqualified": "不合格"}.get(status_filter or "", "")
    target = "全部" if unlimited else str(limit)
    imported_keys: set[str] = set() if reset else _load_imported_file_keys()
    if skip_imported and imported_keys:
        print(f"已入库源文件 {len(imported_keys)} 个，将跳过")
    workers = max(workers, 1)
    if workers > 1:
        print(f"并行解析进程数: {workers}")
    print(f"发现源文件 {len(files)} 个，目标导入 {target} 条{label}记录…")

    imported = 0
    parsed_files = 0
    skipped_imported = 0
    skipped_empty = 0
    failed_files: list[str] = []
    review_rows: list[dict[str, str]] = []
    next_id = 1
    global_category_map: dict[str, str] = {}
    pending_batch: list[tuple[Record, int]] = []
    started = time.time()

    with connection() as conn, conn.cursor() as cur:
        if not reset:
            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
            next_id = int(cur.fetchone()["n"])

        def flush_batch() -> None:
            nonlocal pending_batch, next_id
            if not pending_batch:
                return
            cur.execute("SELECT GET_LOCK('inspection_base_id_alloc', 120)")
            try:
                cur.execute("SELECT COALESCE(MAX(id), 0) AS n FROM inspection_base")
                max_id = int(cur.fetchone()["n"])
                reassigned = [
                    (record, max_id + 1 + i)
                    for i, (record, _) in enumerate(pending_batch)
                ]
                next_id = max_id + 1 + len(pending_batch)
                insert_records_batch(cur, reassigned)
                pending_batch = []
            finally:
                cur.execute("SELECT RELEASE_LOCK('inspection_base_id_alloc')")

        def report_progress() -> None:
            if imported <= 0 or imported % _PROGRESS_EVERY != 0:
                return
            elapsed = time.time() - started
            rate = imported / elapsed if elapsed > 0 else 0
            print(
                f"已导入 {imported} 条，文件 {parsed_files}，{rate:.0f} 条/秒 …",
                flush=True,
            )

        pending_queue: list[str] = []
        for filepath in files:
            if not unlimited and imported >= (limit or 0):
                break
            if skip_imported:
                rel_key = source_relative_key(filepath)
                if rel_key and rel_key in imported_keys:
                    skipped_imported += 1
                    continue
            pending_queue.append(filepath)

        if workers > 1 and pending_queue:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_parse_file_worker, fp): fp for fp in pending_queue}
                for future in as_completed(futures):
                    if not unlimited and imported >= (limit or 0):
                        break
                    filepath, records, err = future.result()
                    if err:
                        failed_files.append(f"{filepath}\t{err}")
                        continue
                    if not records:
                        skipped_empty += 1
                        continue
                    imported, next_id, n_files, global_category_map, pending_batch = _ingest_parsed_file(
                        filepath,
                        records,
                        imported_keys=imported_keys,
                        skip_imported=skip_imported,
                        status_filter=status_filter,
                        unlimited=unlimited,
                        limit=limit,
                        imported=imported,
                        next_id=next_id,
                        global_category_map=global_category_map,
                        pending_batch=pending_batch,
                        review_csv=review_csv,
                        review_rows=review_rows,
                    )
                    parsed_files += n_files
                    if len(pending_batch) >= _BATCH_SIZE:
                        flush_batch()
                    if skip_imported and parsed_files % 10 == 0:
                        print(
                            f"进度：本批已解析 {parsed_files} 个新文件，累计入库 {imported} 条…",
                            flush=True,
                        )
                    report_progress()
        else:
            for filepath in pending_queue:
                if not unlimited and imported >= (limit or 0):
                    break
                filepath, records, err = _parse_file_worker(filepath)
                if err:
                    failed_files.append(f"{filepath}\t{err}")
                    continue
                if not records:
                    skipped_empty += 1
                    continue
                imported, next_id, n_files, global_category_map, pending_batch = _ingest_parsed_file(
                    filepath,
                    records,
                    imported_keys=imported_keys,
                    skip_imported=skip_imported,
                    status_filter=status_filter,
                    unlimited=unlimited,
                    limit=limit,
                    imported=imported,
                    next_id=next_id,
                    global_category_map=global_category_map,
                    pending_batch=pending_batch,
                    review_csv=review_csv,
                    review_rows=review_rows,
                )
                parsed_files += n_files
                if len(pending_batch) >= _BATCH_SIZE:
                    flush_batch()
                report_progress()

        flush_batch()
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
        cur.execute(f"ALTER TABLE inspection_base AUTO_INCREMENT = {int(cur.fetchone()['n'])}")

    create_compat_view()

    elapsed = time.time() - started
    print(
        f"完成：导入 {imported} 条，新解析文件 {parsed_files} 个，"
        f"跳过已入库 {skipped_imported} 个，解析为空 {skipped_empty} 个，"
        f"耗时 {elapsed/60:.1f} 分钟"
    )

    log_dir = Path(OUTPUT_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    if review_csv is not None and review_rows:
        review_csv.parent.mkdir(parents=True, exist_ok=True)
        with review_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(review_rows[0].keys()))
            writer.writeheader()
            writer.writerows(review_rows)
        print(f"校验样本 CSV: {review_csv}")

    if failed_files:
        fail_log = log_dir / "import_v2_failed_files.tsv"
        fail_log.write_text("\n".join(failed_files), encoding="utf-8")
        print(f"解析失败文件 {len(failed_files)} 个，见 {fail_log}")

    summary = log_dir / "import_v2_summary.txt"
    summary.write_text(
        "\n".join(
            [
                f"imported={imported}",
                f"parsed_files={parsed_files}",
                f"skipped_imported={skipped_imported}",
                f"skipped_empty={skipped_empty}",
                f"failed_files={len(failed_files)}",
                f"source_files_total={len(files)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Z 盘源文件导入五表数据库")
    parser.add_argument("--limit", type=int, default=1000, help="导入记录数上限（默认 1000）")
    parser.add_argument("--all", action="store_true", help="全量导入 Z 盘所有源文件")
    parser.add_argument(
        "--status",
        choices=("qualified", "unqualified"),
        default=None,
        help="仅导入合格或不合格记录",
    )
    parser.add_argument("--no-reset", action="store_true", help="不清空已有五表数据，追加导入")
    parser.add_argument(
        "--skip-imported",
        action="store_true",
        help="跳过数据库中已有 file_source 的源文件（配合 --no-reset 补导入）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="并行解析进程数（默认 4，Excel 加速明显）",
    )
    parser.add_argument(
        "--province",
        default=None,
        help="仅导入指定省份目录，例如 广东省",
    )
    parser.add_argument(
        "--only-ext",
        default=None,
        help="仅导入指定扩展名，例如 xlsx 或 pdf",
    )
    parser.add_argument("--review-csv", type=Path, default=None)
    args = parser.parse_args()

    if args.all:
        limit = None
        review_csv = None
    else:
        limit = args.limit
        review_csv = args.review_csv
        if review_csv is None:
            if args.status == "unqualified":
                review_csv = Path(OUTPUT_DIR) / f"import_v2_review_unqualified_{args.limit}.csv"
            elif args.status == "qualified":
                review_csv = Path(OUTPUT_DIR) / f"import_v2_review_qualified_{args.limit}.csv"
            else:
                review_csv = Path(OUTPUT_DIR) / f"import_v2_review_{args.limit}.csv"

    return import_from_files(
        limit=limit,
        reset=not args.no_reset,
        review_csv=review_csv,
        status_filter=args.status,
        skip_imported=args.skip_imported,
        workers=args.workers,
        province=args.province,
        only_ext=args.only_ext,
    )


if __name__ == "__main__":
    raise SystemExit(main())
