"""扫描与缓存合并：已解析文件保留，仅处理新增/未入库文件。"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable

from food_inspection.parser import (
    DATA_ROOT,
    is_non_inspection_detail_file,
    is_planned_sampling_file,
    iter_excel_files,
    parse_file,
    record_to_dict,
)
from food_inspection.analytics import count_qualified_items, count_unqualified_items
from food_inspection.parser.fields import (
    resolve_folder_city,
    resolve_folder_province,
    source_relative_key,
)


def count_skipped_files() -> tuple[int, int, int]:
    """返回 (全库文件数, 计划清单数, 非明细附件数)。"""
    total = skipped_planned = skipped_non_detail = 0
    for filepath in iter_excel_files():
        total += 1
        if is_planned_sampling_file(filepath):
            skipped_planned += 1
        elif is_non_inspection_detail_file(filepath):
            skipped_non_detail += 1
    return total, skipped_planned, skipped_non_detail


def _should_skip_file(filepath: str) -> bool:
    return is_planned_sampling_file(filepath) or is_non_inspection_detail_file(filepath)


def _filter_stat_file_paths(paths: list[str]) -> list[str]:
    return [p for p in paths if p and not _should_skip_file(p)]


def normalize_path(filepath: str) -> str:
    return os.path.normcase(os.path.normpath(filepath))


def build_current_file_index() -> dict[str, str]:
    """relative_key -> 当前磁盘上的规范绝对路径。"""
    index: dict[str, str] = {}
    for filepath in iter_excel_files():
        if _should_skip_file(filepath):
            continue
        key = source_relative_key(filepath)
        if key:
            index[key] = normalize_path(filepath)
    return index


def _canonicalize_stat_paths(paths: list[str], file_index: dict[str, str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if not path:
            continue
        key = source_relative_key(path)
        canonical = file_index.get(key) if key else None
        chosen = canonical or normalize_path(path)
        if chosen in seen:
            continue
        seen.add(chosen)
        result.append(chosen)
    return result


def reconcile_cache_records(
    qualified: list[dict],
    unqualified: list[dict],
    *,
    file_index: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], dict[str, int]]:
    """去除跨平台路径叠加的重复记录，并将 source_file 规范到当前 DATA_ROOT。"""
    file_index = file_index or build_current_file_index()

    def _process_bucket(records: list[dict]) -> tuple[list[dict], int]:
        by_key: dict[str, list[dict]] = {}
        no_key: list[dict] = []
        dropped_orphans = 0

        for rec in records:
            source = rec.get("source_file") or ""
            key = source_relative_key(source)
            if not key:
                no_key.append(rec)
                continue
            if key not in file_index:
                dropped_orphans += 1
                continue
            by_key.setdefault(key, []).append(rec)

        kept: list[dict] = []
        dropped_stale = 0
        for key, group in by_key.items():
            canonical = file_index[key]
            canonical_recs = [
                rec
                for rec in group
                if normalize_path(rec.get("source_file") or "") == canonical
            ]
            stale_recs = [
                rec
                for rec in group
                if normalize_path(rec.get("source_file") or "") != canonical
            ]
            if canonical_recs:
                kept.extend(canonical_recs)
                dropped_stale += len(stale_recs)
                continue
            for rec in stale_recs:
                updated = dict(rec)
                updated["source_file"] = canonical
                updated["source_file_name"] = os.path.basename(canonical)
                kept.append(updated)

        return kept + no_key, dropped_orphans + dropped_stale

    new_qualified, dropped_q = _process_bucket(qualified)
    new_unqualified, dropped_u = _process_bucket(unqualified)
    return new_qualified, new_unqualified, {
        "dropped_duplicate_records": dropped_q + dropped_u,
        "unique_files": len(
            {
                source_relative_key(rec.get("source_file") or "")
                for rec in new_qualified + new_unqualified
                if source_relative_key(rec.get("source_file") or "")
            }
        ),
    }


def collect_indexed_paths(cached: dict | None) -> tuple[set[str], set[str]]:
    """返回 (已成功入库的文件相对键, 已尝试但无数据的文件相对键)。"""
    parsed: set[str] = set()
    empty: set[str] = set()
    if not cached:
        return parsed, empty

    for bucket in ("qualified", "unqualified"):
        for rec in cached.get(bucket, []):
            source = rec.get("source_file")
            if source:
                key = source_relative_key(source)
                if key:
                    parsed.add(key)

    scan_info = cached.get("scan_info", {})
    for source in scan_info.get("empty_file_paths", []):
        if source:
            key = source_relative_key(source)
            if key:
                empty.add(key)
    for source in scan_info.get("failed_file_paths", []):
        if source:
            key = source_relative_key(source)
            if key:
                empty.add(key)

    return parsed, empty


def _ensure_province(stats: dict[str, dict[str, int]], prov: str) -> dict[str, int]:
    return stats.setdefault(
        prov,
        {
            "qualified": 0,
            "unqualified": 0,
            "files": 0,
            "qualified_files": 0,
            "unqualified_files": 0,
        },
    )


def repair_record_locations(records: list[dict]) -> tuple[list[dict], int]:
    """根据源文件路径修正 source_province / source_city（含 import_failed_files）。"""
    repaired: list[dict] = []
    changed = 0
    for rec in records:
        filepath = rec.get("source_file") or ""
        if not filepath:
            repaired.append(rec)
            continue
        path_province = resolve_folder_province(rec)
        path_city = resolve_folder_city(rec)
        if (
            path_province == rec.get("source_province")
            and path_city == rec.get("source_city")
        ):
            repaired.append(rec)
            continue
        updated = dict(rec)
        if path_province:
            updated["source_province"] = path_province
        if path_city:
            updated["source_city"] = path_city
        repaired.append(updated)
        changed += 1
    return repaired, changed


def rebuild_province_stats(qualified: list[dict], unqualified: list[dict]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    files_by_prov: dict[str, set[str]] = {}
    q_files: dict[str, set[str]] = {}
    u_files: dict[str, set[str]] = {}

    for rec in qualified:
        prov = resolve_folder_province(rec) or rec.get("province") or "未知"
        info = _ensure_province(stats, prov)
        info["qualified"] += 1
        source = normalize_path(rec.get("source_file") or "")
        if source:
            files_by_prov.setdefault(prov, set()).add(source)
            q_files.setdefault(prov, set()).add(source)

    for rec in unqualified:
        prov = resolve_folder_province(rec) or rec.get("province") or "未知"
        info = _ensure_province(stats, prov)
        info["unqualified"] += 1
        source = normalize_path(rec.get("source_file") or "")
        if source:
            files_by_prov.setdefault(prov, set()).add(source)
            u_files.setdefault(prov, set()).add(source)

    for prov, files in files_by_prov.items():
        info = _ensure_province(stats, prov)
        info["files"] = len(files)
        info["qualified_files"] = len(q_files.get(prov, set()))
        info["unqualified_files"] = len(u_files.get(prov, set()))

    return stats


def _append_records(records: list, qualified: list[dict], unqualified: list[dict]) -> None:
    for rec in records:
        item = record_to_dict(rec)
        if rec.status == "qualified":
            qualified.append(item)
        else:
            unqualified.append(item)


def _finalize_scan_payload(
    *,
    qualified: list[dict],
    unqualified: list[dict],
    cached: dict | None,
    full_rescan: bool,
    empty_files: list[str],
    failed_files: list[str],
    skipped_planned: int,
    skipped_non_detail: int,
    total: int,
    work_count: int,
    scan_mode: str,
    start_ts: datetime,
    extra_scan_info: dict[str, Any] | None = None,
    empty_file_paths_override: list[str] | None = None,
    failed_file_paths_override: list[str] | None = None,
) -> dict:
    file_index = build_current_file_index()
    qualified, unqualified, _reconcile_info = reconcile_cache_records(
        qualified,
        unqualified,
        file_index=file_index,
    )
    effective_total = total - skipped_planned - skipped_non_detail
    parsed_paths = {
        normalize_path(rec.get("source_file") or "")
        for rec in qualified + unqualified
        if rec.get("source_file")
    }
    parsed_file_count = len(parsed_paths)

    if empty_file_paths_override is not None:
        empty_file_paths = _canonicalize_stat_paths(
            _filter_stat_file_paths(sorted(empty_file_paths_override)),
            file_index,
        )
    else:
        prior_empty = (
            [p for p in cached.get("scan_info", {}).get("empty_file_paths", []) if p]
            if cached and not full_rescan
            else []
        )
        empty_index = {normalize_path(p): p for p in prior_empty}
        for path in empty_files:
            empty_index[normalize_path(path)] = path
        empty_file_paths = _canonicalize_stat_paths(
            _filter_stat_file_paths(sorted(empty_index.values())),
            file_index,
        )

    if failed_file_paths_override is not None:
        failed_file_paths = _canonicalize_stat_paths(
            _filter_stat_file_paths(sorted(failed_file_paths_override)),
            file_index,
        )
    else:
        prior_failed = (
            [p for p in cached.get("scan_info", {}).get("failed_file_paths", []) if p]
            if cached and not full_rescan
            else []
        )
        failed_index = {normalize_path(p): p for p in prior_failed}
        for path in failed_files:
            failed_index[normalize_path(path)] = path
        failed_file_paths = _canonicalize_stat_paths(
            _filter_stat_file_paths(sorted(failed_index.values())),
            file_index,
        )

    province_stats = rebuild_province_stats(qualified, unqualified)
    duration = (datetime.now() - start_ts).total_seconds()
    scan_info: dict[str, Any] = {
        "data_root": DATA_ROOT,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(duration, 1),
        "scan_mode": scan_mode,
        "new_files_processed": work_count,
        "failed_samples": failed_file_paths[:20],
        "empty_file_paths": empty_file_paths,
        "failed_file_paths": failed_file_paths,
    }
    if extra_scan_info:
        scan_info.update(extra_scan_info)

    return {
        "qualified": qualified,
        "unqualified": unqualified,
        "stats": {
            "qualified_count": count_qualified_items(qualified),
            "unqualified_count": count_unqualified_items(unqualified),
            "total_files": effective_total,
            "parsed_files": parsed_file_count,
            "skipped_planned_files": skipped_planned,
            "skipped_non_detail_files": skipped_non_detail,
            "empty_files": max(
                effective_total - parsed_file_count - len(failed_file_paths), 0
            ),
            "failed_files": len(failed_file_paths),
            "provinces": province_stats,
        },
        "scan_info": scan_info,
    }


def repair_cache_payload(cached: dict) -> dict:
    """修复跨平台路径叠加导致的重复记录与文件统计偏差。"""
    qualified, unqualified, reconcile_info = reconcile_cache_records(
        cached.get("qualified", []),
        cached.get("unqualified", []),
    )
    qualified, changed_q = repair_record_locations(qualified)
    unqualified, changed_u = repair_record_locations(unqualified)
    total, skipped_planned, skipped_non_detail = count_skipped_files()
    effective_total = total - skipped_planned - skipped_non_detail
    file_index = build_current_file_index()

    parsed_paths = {
        normalize_path(rec.get("source_file") or "")
        for rec in qualified + unqualified
        if rec.get("source_file")
    }
    scan_info = dict(cached.get("scan_info", {}))
    scan_info["empty_file_paths"] = _canonicalize_stat_paths(
        _filter_stat_file_paths(scan_info.get("empty_file_paths", [])),
        file_index,
    )
    scan_info["failed_file_paths"] = _canonicalize_stat_paths(
        _filter_stat_file_paths(scan_info.get("failed_file_paths", [])),
        file_index,
    )
    scan_info["cache_repaired_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_info["dropped_duplicate_records"] = reconcile_info.get(
        "dropped_duplicate_records", 0
    )
    scan_info["locations_repaired"] = changed_q + changed_u

    return {
        "qualified": qualified,
        "unqualified": unqualified,
        "stats": {
            "qualified_count": count_qualified_items(qualified),
            "unqualified_count": count_unqualified_items(unqualified),
            "total_files": effective_total,
            "parsed_files": len(parsed_paths),
            "skipped_planned_files": skipped_planned,
            "skipped_non_detail_files": skipped_non_detail,
            "empty_files": max(
                effective_total - len(parsed_paths) - len(scan_info["failed_file_paths"]),
                0,
            ),
            "failed_files": len(scan_info["failed_file_paths"]),
            "provinces": rebuild_province_stats(qualified, unqualified),
        },
        "scan_info": scan_info,
    }


def retry_empty_files(
    *,
    cached: dict | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict:
    """仅重试缓存中标记为「空文件」的路径，已成功入库的不动。"""
    if not cached:
        raise ValueError("retry_empty 需要已有 data_cache.json")

    start_ts = datetime.now()
    qualified: list[dict] = list(cached.get("qualified", []))
    unqualified: list[dict] = list(cached.get("unqualified", []))
    known_parsed, _ = collect_indexed_paths(cached)

    prior_empty = cached.get("scan_info", {}).get("empty_file_paths", []) or []
    empty_index = {normalize_path(p): p for p in prior_empty if p}

    for norm in list(empty_index.keys()):
        path = empty_index[norm]
        if _should_skip_file(path):
            empty_index.pop(norm, None)

    work_files: list[str] = []
    for norm, path in empty_index.items():
        if norm in known_parsed:
            continue
        if os.path.isfile(path):
            work_files.append(path)

    recovered = 0
    still_empty = 0
    new_failed: list[str] = []

    for i, filepath in enumerate(work_files, 1):
        if progress_cb:
            progress_cb(i, len(work_files), f"重试空文件 {i}/{len(work_files)}")

        norm = normalize_path(filepath)
        try:
            records = parse_file(filepath)
            if records:
                _append_records(records, qualified, unqualified)
                empty_index.pop(norm, None)
                recovered += 1
            else:
                still_empty += 1
        except Exception:
            empty_index.pop(norm, None)
            new_failed.append(filepath)

    total, skipped_planned, skipped_non_detail = count_skipped_files()

    return _finalize_scan_payload(
        qualified=qualified,
        unqualified=unqualified,
        cached=cached,
        full_rescan=False,
        empty_files=[],
        failed_files=new_failed,
        skipped_planned=skipped_planned,
        skipped_non_detail=skipped_non_detail,
        total=total,
        work_count=len(work_files),
        scan_mode="retry_empty",
        start_ts=start_ts,
        empty_file_paths_override=sorted(empty_index.values()),
        extra_scan_info={
            "retry_empty_candidates": len(work_files),
            "retry_empty_recovered": recovered,
            "retry_empty_still_empty": still_empty,
        },
    )


def scan_pdf_files(
    *,
    cached: dict | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict:
    """重扫全库所有 PDF：清除旧 PDF 记录后重新解析并合并入库。"""
    if not cached:
        raise ValueError("scan_pdf 需要已有 data_cache.json")

    start_ts = datetime.now()

    def _is_pdf(path: str) -> bool:
        return (path or "").lower().endswith(".pdf")

    qualified: list[dict] = [
        r for r in cached.get("qualified", []) if not _is_pdf(r.get("source_file") or "")
    ]
    unqualified: list[dict] = [
        r for r in cached.get("unqualified", []) if not _is_pdf(r.get("source_file") or "")
    ]

    prior_empty = [
        p
        for p in (cached.get("scan_info", {}).get("empty_file_paths", []) or [])
        if p and not _is_pdf(p)
    ]
    prior_failed = [
        p
        for p in (cached.get("scan_info", {}).get("failed_file_paths", []) or [])
        if p and not _is_pdf(p)
    ]

    work_files: list[str] = []
    for filepath in iter_excel_files():
        if not _is_pdf(filepath):
            continue
        if _should_skip_file(filepath):
            continue
        if os.path.isfile(filepath):
            work_files.append(filepath)

    recovered = 0
    empty_files: list[str] = []
    failed_files: list[str] = []

    for i, filepath in enumerate(work_files, 1):
        if progress_cb:
            progress_cb(i, len(work_files), f"扫描 PDF {i}/{len(work_files)}")

        try:
            records = parse_file(filepath)
            if records:
                _append_records(records, qualified, unqualified)
                recovered += 1
            else:
                empty_files.append(filepath)
        except Exception:
            failed_files.append(filepath)

    total, skipped_planned, skipped_non_detail = count_skipped_files()

    return _finalize_scan_payload(
        qualified=qualified,
        unqualified=unqualified,
        cached=cached,
        full_rescan=False,
        empty_files=[],
        failed_files=[],
        skipped_planned=skipped_planned,
        skipped_non_detail=skipped_non_detail,
        total=total,
        work_count=len(work_files),
        scan_mode="scan_pdf",
        start_ts=start_ts,
        empty_file_paths_override=sorted(prior_empty + empty_files),
        failed_file_paths_override=sorted(prior_failed + failed_files),
        extra_scan_info={
            "scan_pdf_candidates": len(work_files),
            "scan_pdf_recovered": recovered,
            "scan_pdf_still_empty": len(empty_files),
            "scan_pdf_failed": len(failed_files),
        },
    )


def retry_failed_files(
    *,
    cached: dict | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    path_filter: Callable[[str], bool] | None = None,
) -> dict:
    """重试缓存中标记为读取异常的文件（修复解析逻辑后补入库）。"""
    if not cached:
        raise ValueError("retry_failed 需要已有 data_cache.json")

    start_ts = datetime.now()
    qualified: list[dict] = list(cached.get("qualified", []))
    unqualified: list[dict] = list(cached.get("unqualified", []))
    known_parsed, _ = collect_indexed_paths(cached)

    prior_failed = cached.get("scan_info", {}).get("failed_file_paths", []) or []
    failed_index = {normalize_path(p): p for p in prior_failed if p}
    prior_empty = cached.get("scan_info", {}).get("empty_file_paths", []) or []
    empty_index = {normalize_path(p): p for p in prior_empty if p}

    work_files: list[str] = []
    for norm, path in list(failed_index.items()):
        if path_filter and not path_filter(path):
            continue
        if _should_skip_file(path):
            failed_index.pop(norm, None)
            continue
        if norm in known_parsed:
            failed_index.pop(norm, None)
            continue
        if os.path.isfile(path):
            work_files.append(path)

    recovered = 0
    still_failed = 0
    moved_empty = 0

    for i, filepath in enumerate(work_files, 1):
        if progress_cb:
            progress_cb(i, len(work_files), f"重试异常文件 {i}/{len(work_files)}")

        norm = normalize_path(filepath)
        try:
            records = parse_file(filepath)
        except Exception:
            still_failed += 1
            continue

        failed_index.pop(norm, None)
        if records:
            _append_records(records, qualified, unqualified)
            recovered += 1
        else:
            empty_index[norm] = filepath
            moved_empty += 1

    total, skipped_planned, skipped_non_detail = count_skipped_files()

    return _finalize_scan_payload(
        qualified=qualified,
        unqualified=unqualified,
        cached=cached,
        full_rescan=False,
        empty_files=[],
        failed_files=[],
        skipped_planned=skipped_planned,
        skipped_non_detail=skipped_non_detail,
        total=total,
        work_count=len(work_files),
        scan_mode="retry_failed",
        start_ts=start_ts,
        empty_file_paths_override=sorted(empty_index.values()),
        failed_file_paths_override=sorted(failed_index.values()),
        extra_scan_info={
            "retry_failed_candidates": len(work_files),
            "retry_failed_recovered": recovered,
            "retry_failed_still_failed": still_failed,
            "retry_failed_moved_empty": moved_empty,
        },
    )


def count_pending_work(cached: dict | None, *, full_rescan: bool = False) -> dict[str, int]:
    """统计待处理文件数（不读取文件内容）。"""
    from food_inspection.parser import is_non_inspection_detail_file, is_planned_sampling_file

    known_parsed, known_empty = collect_indexed_paths(cached)
    if full_rescan:
        known_parsed = set()
        known_empty = set()

    pending_new = 0
    skipped_planned = 0
    skipped_non_detail = 0
    total = 0

    for filepath in iter_excel_files():
        total += 1
        if is_planned_sampling_file(filepath):
            skipped_planned += 1
            continue
        if is_non_inspection_detail_file(filepath):
            skipped_non_detail += 1
            continue
        key = source_relative_key(filepath)
        if full_rescan or (key not in known_parsed and key not in known_empty):
            pending_new += 1

    effective_total = total - skipped_planned - skipped_non_detail
    parsed_count = min(len(known_parsed), effective_total)
    return {
        "total_files": effective_total,
        "parsed_files": parsed_count,
        "pending_new": pending_new,
        "skipped_planned": skipped_planned,
        "skipped_non_detail": skipped_non_detail,
        "unindexed": max(effective_total - parsed_count, 0),
    }


def scan_files(
    *,
    cached: dict | None = None,
    full_rescan: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict:
    """扫描 Excel 并更新缓存。

    - 默认增量：保留已有记录，仅解析新增或未入库文件
    - full_rescan=True：全量重扫（覆盖旧数据）
    """
    start_ts = datetime.now()
    qualified: list[dict] = []
    unqualified: list[dict] = []
    failed_files: list[str] = []
    empty_files: list[str] = []
    skipped_planned = 0
    skipped_non_detail = 0

    known_parsed, known_empty = collect_indexed_paths(cached)
    if full_rescan:
        known_parsed = set()
        known_empty = set()
    elif cached:
        qualified.extend(cached.get("qualified", []))
        unqualified.extend(cached.get("unqualified", []))
        qualified, unqualified, _ = reconcile_cache_records(qualified, unqualified)

    all_files = list(iter_excel_files())
    total = len(all_files)
    work_files: list[str] = []

    for filepath in all_files:
        if is_planned_sampling_file(filepath):
            skipped_planned += 1
            continue
        if is_non_inspection_detail_file(filepath):
            skipped_non_detail += 1
            continue
        key = source_relative_key(filepath)
        if full_rescan or (key not in known_parsed and key not in known_empty):
            work_files.append(filepath)

    for i, filepath in enumerate(work_files, 1):
        if progress_cb:
            label = "全量扫描" if full_rescan else "新增扫描"
            progress_cb(i, len(work_files), f"{label} {i}/{len(work_files)}")

        try:
            records = parse_file(filepath)
            if not records:
                empty_files.append(filepath)
                continue
            _append_records(records, qualified, unqualified)
        except Exception:
            failed_files.append(filepath)

    scan_mode = "full" if full_rescan else "incremental"
    return _finalize_scan_payload(
        qualified=qualified,
        unqualified=unqualified,
        cached=cached,
        full_rescan=full_rescan,
        empty_files=empty_files,
        failed_files=failed_files,
        skipped_planned=skipped_planned,
        skipped_non_detail=skipped_non_detail,
        total=total,
        work_count=len(work_files),
        scan_mode=scan_mode,
        start_ts=start_ts,
    )
