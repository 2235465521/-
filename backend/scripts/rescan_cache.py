"""扫描 Excel 并更新 data_cache.json（默认增量，仅处理新文件）。"""

from __future__ import annotations

import scripts._bootstrap  # noqa: F401

import argparse
import json
import os
import sys

from food_inspection.scan import (
    retry_empty_files,
    retry_failed_files,
    scan_files,
    scan_pdf_files,
)

from config import CACHE_FILE, ROOT_DIR


def _load_cache() -> dict | None:
    if not os.path.isfile(CACHE_FILE):
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def rescan(
    *,
    full: bool = False,
    retry_empty: bool = False,
    retry_failed: bool = False,
    scan_pdf: bool = False,
) -> dict:
    sys.stdout.reconfigure(encoding="utf-8")
    if sum((full, retry_empty, retry_failed, scan_pdf)) > 1:
        print("不能同时使用 --full、--retry-empty、--retry-failed、--pdf", file=sys.stderr)
        sys.exit(2)

    cached = None if full else _load_cache()
    if (retry_empty or retry_failed) and not cached:
        print("未找到缓存，无法重试", file=sys.stderr)
        sys.exit(1)

    mode = (
        "重扫全库 PDF"
        if scan_pdf
        else (
            "重试异常文件"
            if retry_failed
            else ("重试空文件" if retry_empty else ("全量" if full else "增量"))
        )
    )

    if cached and not full:
        parsed = len({r.get("source_file") for r in cached.get("qualified", []) + cached.get("unqualified", []) if r.get("source_file")})
        print(f"已有缓存：合格 {cached.get('stats', {}).get('qualified_count', 0)} 条，已入库文件约 {parsed} 个", flush=True)
        if retry_empty:
            empty_n = len(cached.get("scan_info", {}).get("empty_file_paths", []))
            print(f"缓存中空文件标记: {empty_n} 个", flush=True)
        if retry_failed:
            failed_n = len(cached.get("scan_info", {}).get("failed_file_paths", []))
            print(f"缓存中异常文件标记: {failed_n} 个", flush=True)

    def _progress(current: int, total: int, message: str) -> None:
        step = 10 if scan_pdf else 50
        if current % step == 0 or current == total or current == 1:
            print(f"  {message}", flush=True)

    print(f"开始{mode}...", flush=True)
    if scan_pdf:
        payload = scan_pdf_files(cached=cached, progress_cb=_progress)
    elif retry_empty:
        payload = retry_empty_files(cached=cached, progress_cb=_progress)
    elif retry_failed:
        payload = retry_failed_files(cached=cached, progress_cb=_progress)
    else:
        payload = scan_files(cached=cached, full_rescan=full, progress_cb=_progress)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    stats = payload["stats"]
    info = payload["scan_info"]
    print("\n扫描完成")
    print(f"  模式: {info.get('scan_mode')}")
    print(f"  本次处理: {info.get('new_files_processed', 0)} 个文件")
    if info.get("scan_mode") == "retry_empty":
        print(f"  补入成功: {info.get('retry_empty_recovered', 0)} 个")
        print(f"  仍为空: {info.get('retry_empty_still_empty', 0)} 个")
    if info.get("scan_mode") == "retry_failed":
        print(f"  补入成功: {info.get('retry_failed_recovered', 0)} 个")
        print(f"  仍异常: {info.get('retry_failed_still_failed', 0)} 个")
        print(f"  改为空文件: {info.get('retry_failed_moved_empty', 0)} 个")
    if info.get("scan_mode") == "scan_pdf":
        print(f"  PDF 总数: {info.get('scan_pdf_candidates', 0)} 个")
        print(f"  解析成功: {info.get('scan_pdf_recovered', 0)} 个")
        print(f"  仍为空: {info.get('scan_pdf_still_empty', 0)} 个")
        print(f"  读取异常: {info.get('scan_pdf_failed', 0)} 个")
    print(f"  有效文件: {stats['parsed_files']}/{stats['total_files']}")
    if stats.get("skipped_planned_files"):
        print(f"  计划清单(未纳入统计): {stats['skipped_planned_files']}")
    if stats.get("skipped_non_detail_files"):
        print(f"  非明细附件(未纳入统计): {stats['skipped_non_detail_files']}")
    print(f"  合格记录: {stats['qualified_count']}")
    print(f"  不合格记录: {stats['unqualified_count']}")
    print(f"  读取异常: {stats['failed_files']}")
    print(f"  耗时: {info['duration_seconds']} 秒")
    print(f"  已保存: {CACHE_FILE}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="扫描 Excel 更新缓存")
    parser.add_argument("--full", action="store_true", help="全量重扫（覆盖已有数据）")
    parser.add_argument(
        "--retry-empty",
        action="store_true",
        help="仅重试缓存中标记为空、但实际可能有数据的文件",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="重试缓存中标记为读取异常的文件（修复解析后补入库）",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="重扫全库所有 PDF（清除旧 PDF 记录后重新解析）",
    )
    args = parser.parse_args()
    rescan(
        full=args.full,
        retry_empty=args.retry_empty,
        retry_failed=args.retry_failed,
        scan_pdf=args.pdf,
    )
