
"""在 PDF 目录中按标准号发现磁盘文件（数据库无 filepath 记录时使用）。"""

from __future__ import annotations

import fnmatch
import re
import threading
import time
from pathlib import Path

from paths import PDF_ROOT, PDF_SEARCH_ROOT
from core.std_normalize import filename_contains_std_id, std_id_glob_patterns

# Thread-safe in-memory cache for all PDF files in PDF_ROOT and PDF_SEARCH_ROOT
_DISK_PDF_CACHE_LOCK = threading.Lock()
_DISK_PDF_CACHE_TIME = 0.0
_DISK_PDF_CACHE: list[Path] = []
_DISK_PDF_PATHS_SET: set[str] = set()
_DISK_PDF_SCANNING = False  # Track if a background scan is running
CACHE_TTL = 1800.0  # Cache for 30 minutes to avoid frequent disk array traversal


def _bg_scan() -> None:
    """Background thread worker to perform the actual rglob scanning without blocking requests."""
    global _DISK_PDF_CACHE, _DISK_PDF_CACHE_TIME, _DISK_PDF_SCANNING, _DISK_PDF_PATHS_SET
    try:
        found_files: list[Path] = []
        seen_paths: set[str] = set()
        last_update_time = time.time()

        for root in (PDF_ROOT, PDF_SEARCH_ROOT):
            if not root.is_dir():
                continue
            try:
                for hit in root.rglob("*.pdf"):
                    try:
                        if not hit.is_file():
                            continue
                        key = str(hit).lower()
                        if key not in seen_paths:
                            seen_paths.add(key)
                            found_files.append(hit)
                        
                        # Incrementally update the cache so the first request doesn't have to wait for the entire scan
                        now = time.time()
                        if now - last_update_time > 1.5:
                            with _DISK_PDF_CACHE_LOCK:
                                _DISK_PDF_CACHE = list(found_files)
                                _DISK_PDF_PATHS_SET = set(seen_paths)
                                _DISK_PDF_CACHE_TIME = now
                            last_update_time = now
                    except Exception:
                        continue
            except Exception:
                continue

        with _DISK_PDF_CACHE_LOCK:
            _DISK_PDF_CACHE = found_files
            _DISK_PDF_PATHS_SET = set(seen_paths)
            _DISK_PDF_CACHE_TIME = time.time()
    finally:
        with _DISK_PDF_CACHE_LOCK:
            _DISK_PDF_SCANNING = False


def check_file_exists_in_cache(path: Path) -> bool:
    """检查文件是否存在（优先检查直接路径，找不到再比对缓存路径集合）。"""
    try:
        if path.is_file():
            return True
    except Exception:
        pass
    key = str(path).lower()
    with _DISK_PDF_CACHE_LOCK:
        if key in _DISK_PDF_PATHS_SET:
            return True
    return False


import datetime

def start_background_scan() -> None:
    """Start background scan if not already running."""
    global _DISK_PDF_SCANNING
    with _DISK_PDF_CACHE_LOCK:
        if _DISK_PDF_SCANNING:
            return
        _DISK_PDF_SCANNING = True
    t = threading.Thread(target=_bg_scan, name="pdf-disk-scan", daemon=True)
    t.start()


def _seconds_until_next_midnight() -> float:
    now = datetime.datetime.now()
    tomorrow = now.date() + datetime.timedelta(days=1)
    midnight = datetime.datetime.combine(tomorrow, datetime.time.min)
    return max((midnight - now).total_seconds(), 1.0)


def _midnight_scheduler_loop() -> None:
    """后台定时任务：每天夜间 00:00 自动触发全量磁盘扫描"""
    while True:
        try:
            secs = _seconds_until_next_midnight()
            time.sleep(secs)
            start_background_scan()
            time.sleep(5)  # 避免极短时间内重复触发
        except Exception:
            time.sleep(60)


_SCHEDULER_STARTED = False


def init_scheduler_and_warmup() -> None:
    """在服务启动时初始化零点定时器并启动一次后台预热扫描"""
    global _SCHEDULER_STARTED
    with _DISK_PDF_CACHE_LOCK:
        if _SCHEDULER_STARTED:
            return
        _SCHEDULER_STARTED = True

    start_background_scan()
    t = threading.Thread(target=_midnight_scheduler_loop, name="pdf-midnight-scheduler", daemon=True)
    t.start()


# 模块载入时自动初始化定时调度器与后台预热
init_scheduler_and_warmup()


def _get_disk_pdf_list() -> list[Path]:
    """获取所有磁盘 PDF 文件的列表（直接读取内存缓存，绝不阻塞用户 HTTP 请求）"""
    global _DISK_PDF_CACHE
    if not _DISK_PDF_CACHE and not _DISK_PDF_SCANNING:
        start_background_scan()

    with _DISK_PDF_CACHE_LOCK:
        return _DISK_PDF_CACHE



def extract_std_number_digits(std_id: str) -> str | None:
    if not std_id:
        return None
    # If there is a slash (e.g. /T, /Z, /X), standard number is AFTER the slash
    slash_pos = std_id.find("/")
    if slash_pos != -1:
        after_slash = std_id[slash_pos:]
        m = re.search(r'\d+', after_slash)
        if m:
            return m.group(0)
    # Otherwise, find standard number digits (prefer length >= 3)
    matches = re.findall(r'\d+', std_id)
    if not matches:
        return None
    for m in matches:
        if len(m) >= 3:
            return m
    return matches[0]


def discover_pdfs_on_disk(std_id: str, limit: int = 20) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    all_pdfs = _get_disk_pdf_list()

    # Find the main standard number part of the std_id to pre-filter (extremely fast)
    num_part = extract_std_number_digits(std_id)

    # If we have a number part, we only scan files containing it
    if num_part:
        candidates = [hit for hit in all_pdfs if num_part in hit.name]
    else:
        candidates = all_pdfs

    for pattern in std_id_glob_patterns(std_id):
        pattern_lower = pattern.lower()
        for hit in candidates:
            if fnmatch.fnmatch(hit.name.lower(), pattern_lower):
                if filename_contains_std_id(hit.name, std_id):
                    key = str(hit).lower()
                    if key not in seen:
                        seen.add(key)
                        found.append(hit)
                        if len(found) >= limit:
                            return sorted(found, key=lambda p: p.name)

    return sorted(found, key=lambda p: p.name)


def find_pdf_by_filename_on_disk(name: str) -> Path | None:
    """在磁盘 PDF 缓存列表中查找特定文件名的 PDF 文件"""
    name_lower = name.lower()
    for hit in _get_disk_pdf_list():
        if hit.name.lower() == name_lower:
            return hit
    return None


def pdf_display_path(path: Path) -> str:
    try:
        return str(path.absolute().relative_to(PDF_ROOT.absolute()))
    except ValueError:
        try:
            return str(path.resolve().relative_to(PDF_ROOT.resolve()))
        except Exception:
            return path.name

