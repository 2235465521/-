"""解析管道主流程：校验已入库、纠正错误、补导未解析文件。"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from config import DATA_ROOT, OUTPUT_DIR, ROOT_DIR
from food_inspection.db import connection
from food_inspection.mysql_v2 import create_compat_view, insert_records_batch
from food_inspection.parser import (
    is_non_inspection_detail_file,
    is_planned_sampling_file,
    iter_excel_files,
)
from food_inspection.parser.fields import source_relative_key
from food_inspection.parser.models import Record
from food_inspection.pipeline.db_store import (
    delete_file_source,
    load_imported_file_keys,
    load_records_by_file_source,
)
from food_inspection.pipeline.fingerprint import fingerprints_match
from food_inspection.pipeline.guard import guard_file_records, parse_file_guarded

_BATCH = 500
_PROGRESS_EVERY = 200


def _schedule_stats_refresh() -> None:
    """新数据入库后后台刷新预统计与榜单表。"""
    import subprocess
    import threading

    backend_dir = Path(__file__).resolve().parents[2]
    python = sys.executable

    def _run() -> None:
        try:
            print("[管道] 后台刷新预统计与榜单表…", flush=True)
            subprocess.run(
                [python, "-m", "scripts.refresh_stats"],
                cwd=str(backend_dir),
                timeout=7200,
                check=False,
            )
            print("[管道] 预统计与榜单表刷新完成", flush=True)
        except Exception as exc:
            print(f"[管道] 预统计刷新失败: {exc}", flush=True)

    threading.Thread(target=_run, daemon=True, name="stats-refresh").start()


@dataclass
class PipelineResult:
    audited_files: int = 0
    skipped_ok: int = 0
    repaired_files: int = 0
    repaired_rows: int = 0
    row_patched: int = 0
    imported_files: int = 0
    imported_rows: int = 0
    skipped_empty: int = 0
    skipped_structural: int = 0
    skipped_no_disk: int = 0
    failed_files: int = 0
    issues: dict[str, int] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)


def _resolve_disk_path(rel_key: str) -> str:
    rel = (rel_key or "").strip().replace("\\", "/")
    if not rel:
        return ""
    if rel.startswith("/") and os.path.isfile(rel):
        return rel
    joined = os.path.join(DATA_ROOT, rel)
    return joined if os.path.isfile(joined) else ""


def _parse_worker(filepath: str) -> tuple[str, list[Record] | None, str, dict[str, int]]:
    if is_planned_sampling_file(filepath) or is_non_inspection_detail_file(filepath):
        return filepath, None, "structural_skip", {}
    records, err, issues = parse_file_guarded(filepath)
    if err:
        return filepath, None, err, {}
    return filepath, records, "", issues


def _merge_issues(target: dict[str, int], source: dict[str, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def _flush_batch(cur, pending: list[tuple[Record, int]], next_id: int) -> int:
    if not pending:
        return next_id
    cur.execute("SELECT GET_LOCK('inspection_base_id_alloc', 120)")
    try:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS n FROM inspection_base")
        max_id = int(cur.fetchone()["n"])
        reassigned = [(record, max_id + 1 + i) for i, (record, _) in enumerate(pending)]
        next_id = max_id + 1 + len(pending)
        insert_records_batch(cur, reassigned)
        return next_id
    finally:
        cur.execute("SELECT RELEASE_LOCK('inspection_base_id_alloc')")


def run_parse_pipeline(
    *,
    repair_imported: bool = True,
    import_new: bool = True,
    dry_run: bool = False,
    workers: int = 4,
    province: str | None = None,
    limit_files: int | None = None,
) -> PipelineResult:
    """全量或增量：校验已入库文件 + 导入未解析文件。"""
    result = PipelineResult()
    if not Path(DATA_ROOT).is_dir():
        raise FileNotFoundError(f"数据目录不存在: {DATA_ROOT}")

    all_files = list(iter_excel_files())
    if province:
        prefix = f"{province.strip()}/"
        all_files = [
            fp
            for fp in all_files
            if source_relative_key(fp).startswith(prefix)
            or f"/{province.strip()}/" in fp.replace("\\", "/")
        ]
    if limit_files:
        all_files = all_files[:limit_files]

    disk_by_rel: dict[str, str] = {}
    for fp in all_files:
        rel = source_relative_key(fp)
        if rel:
            disk_by_rel[rel] = fp

    imported_keys = load_imported_file_keys()
    db_by_source = load_records_by_file_source() if repair_imported else {}

    audit_targets: list[str] = []
    import_targets: list[str] = []

    if repair_imported:
        for rel in sorted(imported_keys):
            if rel in disk_by_rel:
                audit_targets.append(rel)
    if import_new:
        for rel, fp in sorted(disk_by_rel.items()):
            if rel not in imported_keys:
                import_targets.append(fp)

    print(
        f"管道启动：磁盘文件 {len(disk_by_rel)}，已入库 {len(imported_keys)}，"
        f"待校验 {len(audit_targets)}，待新导入 {len(import_targets)}，"
        f"workers={workers}，dry_run={dry_run}",
        flush=True,
    )

    started = time.time()
    pending: list[tuple[Record, int]] = []
    next_id = 1

    with connection() as conn, conn.cursor() as cur:
        if not dry_run:
            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM inspection_base")
            next_id = int(cur.fetchone()["n"])

        def ingest_records(filepath: str, records: list[Record]) -> int:
            nonlocal next_id, pending
            if dry_run:
                return len(records)
            for record in records:
                pending.append((record, next_id))
                next_id += 1
                if len(pending) >= _BATCH:
                    next_id = _flush_batch(cur, pending, next_id)
                    pending.clear()
            return len(records)

        # --- 阶段 1：校验已入库文件 ---
        if audit_targets and workers > 1:
            paths = [disk_by_rel[rel] for rel in audit_targets]
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_parse_worker, fp): fp for fp in paths}
                done = 0
                for future in as_completed(futures):
                    filepath, records, err, issue_counts = future.result()
                    rel = source_relative_key(filepath) or ""
                    done += 1
                    _merge_issues(result.issues, issue_counts)
                    result.audited_files += 1

                    if err == "structural_skip":
                        result.skipped_structural += 1
                        continue
                    if err:
                        result.failed_files += 1
                        result.log_lines.append(f"FAIL_AUDIT\t{rel}\t{err}")
                        continue

                    db_records = db_by_source.get(rel, [])
                    db_guarded, _ = guard_file_records(list(db_records), filepath)

                    if not records and db_guarded:
                        result.skipped_no_disk += 1
                        result.log_lines.append(f"WARN_EMPTY_REPARSE\t{rel}\t保留库内{len(db_guarded)}条")
                        continue

                    if fingerprints_match(db_guarded, records):
                        result.skipped_ok += 1
                        continue

                    if dry_run:
                        result.repaired_files += 1
                        result.log_lines.append(
                            f"DRY_REPAIR\t{rel}\tdb={len(db_guarded)}\tfresh={len(records)}"
                        )
                        continue

                    deleted = delete_file_source(cur, rel)
                    count = ingest_records(filepath, records)
                    result.repaired_files += 1
                    result.repaired_rows += count
                    result.log_lines.append(
                        f"REPAIRED\t{rel}\tdeleted={deleted}\tinserted={count}"
                    )

                    if done % _PROGRESS_EVERY == 0:
                        print(f"校验进度 {done}/{len(audit_targets)}…", flush=True)
        elif audit_targets:
            for i, rel in enumerate(audit_targets, 1):
                filepath = disk_by_rel[rel]
                records, err, issue_counts = parse_file_guarded(filepath)
                result.audited_files += 1
                if err:
                    result.failed_files += 1
                    result.log_lines.append(f"FAIL_AUDIT\t{rel}\t{err}")
                    continue
                _merge_issues(result.issues, issue_counts)
                db_records = db_by_source.get(rel, [])
                db_guarded, _ = guard_file_records(list(db_records), filepath)
                if not records and db_guarded:
                    result.log_lines.append(f"WARN_EMPTY_REPARSE\t{rel}\t保留库内{len(db_guarded)}条")
                    continue
                if fingerprints_match(db_guarded, records):
                    result.skipped_ok += 1
                    continue
                if dry_run:
                    result.repaired_files += 1
                    continue
                delete_file_source(cur, rel)
                count = ingest_records(filepath, records)
                result.repaired_files += 1
                result.repaired_rows += count
                if i % _PROGRESS_EVERY == 0:
                    print(f"校验进度 {i}/{len(audit_targets)}…", flush=True)

        # --- 阶段 2：导入未解析文件 ---
        new_queue = import_targets
        if new_queue and workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_parse_worker, fp): fp for fp in new_queue}
                done = 0
                for future in as_completed(futures):
                    filepath, records, err, issue_counts = future.result()
                    rel = source_relative_key(filepath) or ""
                    done += 1
                    _merge_issues(result.issues, issue_counts)
                    if err == "structural_skip":
                        result.skipped_structural += 1
                        continue
                    if err:
                        result.failed_files += 1
                        result.log_lines.append(f"FAIL_IMPORT\t{rel}\t{err}")
                        continue
                    if not records:
                        result.skipped_empty += 1
                        continue
                    if dry_run:
                        result.imported_files += 1
                        result.imported_rows += len(records)
                        continue
                    count = ingest_records(filepath, records)
                    result.imported_files += 1
                    result.imported_rows += count
                    if done % _PROGRESS_EVERY == 0:
                        print(f"新导入进度 {done}/{len(new_queue)}…", flush=True)
        elif new_queue:
            for i, filepath in enumerate(new_queue, 1):
                records, err, issue_counts = parse_file_guarded(filepath)
                rel = source_relative_key(filepath) or ""
                if err:
                    result.failed_files += 1
                    result.log_lines.append(f"FAIL_IMPORT\t{rel}\t{err}")
                    continue
                _merge_issues(result.issues, issue_counts)
                if not records:
                    result.skipped_empty += 1
                    continue
                if dry_run:
                    result.imported_files += 1
                    result.imported_rows += len(records)
                    continue
                count = ingest_records(filepath, records)
                result.imported_files += 1
                result.imported_rows += count
                if i % _PROGRESS_EVERY == 0:
                    print(f"新导入进度 {i}/{len(new_queue)}…", flush=True)

        if not dry_run:
            if pending:
                next_id = _flush_batch(cur, pending, next_id)
                pending.clear()
            conn.commit()
            create_compat_view()

    if not dry_run:
        stats_cache = Path(ROOT_DIR) / "data" / "mysql_stats_cache.json"
        if stats_cache.is_file():
            stats_cache.unlink(missing_ok=True)
        analytics_cache = Path(ROOT_DIR) / "data" / "analytics_disk_cache"
        if analytics_cache.is_dir():
            for p in analytics_cache.glob("*.json"):
                try:
                    p.unlink()
                except OSError:
                    pass
        if result.imported_rows > 0 or result.repaired_rows > 0:
            _schedule_stats_refresh()

    elapsed = time.time() - started
    log_dir = Path(OUTPUT_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "parse_pipeline_log.tsv"
    log_path.write_text("\n".join(result.log_lines), encoding="utf-8")

    summary_path = log_dir / "parse_pipeline_summary.txt"
    summary_path.write_text(
        "\n".join(
            [
                f"audited_files={result.audited_files}",
                f"skipped_ok={result.skipped_ok}",
                f"repaired_files={result.repaired_files}",
                f"repaired_rows={result.repaired_rows}",
                f"imported_files={result.imported_files}",
                f"imported_rows={result.imported_rows}",
                f"skipped_empty={result.skipped_empty}",
                f"skipped_structural={result.skipped_structural}",
                f"failed_files={result.failed_files}",
                f"elapsed_sec={elapsed:.1f}",
                f"issues={result.issues}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"完成：校验 {result.audited_files}（跳过一致 {result.skipped_ok}，"
        f"重导 {result.repaired_files}/{result.repaired_rows} 条），"
        f"新导入 {result.imported_files}/{result.imported_rows} 条，"
        f"解析为空 {result.skipped_empty}，失败 {result.failed_files}，"
        f"耗时 {elapsed/60:.1f} 分钟",
        flush=True,
    )
    print(f"日志: {log_path}", flush=True)
    return result
