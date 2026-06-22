"""在 PDF 目录中按标准号发现磁盘文件（数据库无 filepath 记录时使用）。"""

from __future__ import annotations

import fnmatch
import threading
import time
from pathlib import Path

from paths import PDF_ROOT, PDF_SEARCH_ROOT
from core.std_normalize import filename_contains_std_id, std_id_glob_patterns

# Thread-safe in-memory cache for all PDF files in PDF_ROOT and PDF_SEARCH_ROOT
_DISK_PDF_CACHE_LOCK = threading.Lock()
_DISK_PDF_CACHE_TIME = 0.0
_DISK_PDF_CACHE: list[Path] = []
_DISK_PDF_SCANNING = False  # Track if a background scan is running
CACHE_TTL = 1800.0  # Cache for 30 minutes to avoid frequent disk array traversal


def _bg_scan() -> None:
    """Background thread worker to perform the actual rglob scanning without blocking requests."""
    global _DISK_PDF_CACHE, _DISK_PDF_CACHE_TIME, _DISK_PDF_SCANNING
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
                        key = str(hit.resolve()).lower()
                        if key not in seen_paths:
                            seen_paths.add(key)
                            found_files.append(hit)
                        
                        # Incrementally update the cache so the first request doesn't have to wait for the entire scan
                        now = time.time()
                        if now - last_update_time > 1.5:
                            with _DISK_PDF_CACHE_LOCK:
                                _DISK_PDF_CACHE = list(found_files)
                                _DISK_PDF_CACHE_TIME = now
                            last_update_time = now
                    except Exception:
                        continue
            except Exception:
                continue

        with _DISK_PDF_CACHE_LOCK:
            _DISK_PDF_CACHE = found_files
            _DISK_PDF_CACHE_TIME = time.time()
    finally:
        with _DISK_PDF_CACHE_LOCK:
            _DISK_PDF_SCANNING = False


def start_background_scan() -> None:
    """Start background scan if not already running."""
    global _DISK_PDF_SCANNING
    with _DISK_PDF_CACHE_LOCK:
        if _DISK_PDF_SCANNING:
            return
        _DISK_PDF_SCANNING = True
    t = threading.Thread(target=_bg_scan, name="pdf-disk-scan", daemon=True)
    t.start()


def _get_disk_pdf_list() -> list[Path]:
    """获取所有磁盘 PDF 文件的列表（带后台扫描与 30 分钟缓存，避免阻塞 web 请求）"""
    global _DISK_PDF_CACHE, _DISK_PDF_CACHE_TIME
    now = time.time()
    
    cache_empty = not _DISK_PDF_CACHE
    cache_expired = (now - _DISK_PDF_CACHE_TIME >= CACHE_TTL)

    if cache_empty or cache_expired:
        start_background_scan()

    # If the cache is completely empty, wait up to 8 seconds for the background thread to find initial files (checks _DISK_PDF_SCANNING to exit early)
    if cache_empty:
        start_wait = time.time()
        while _DISK_PDF_SCANNING and not _DISK_PDF_CACHE and (time.time() - start_wait < 8.0):
            time.sleep(0.1)

    with _DISK_PDF_CACHE_LOCK:
        return _DISK_PDF_CACHE


def discover_pdfs_on_disk(std_id: str, limit: int = 20) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    all_pdfs = _get_disk_pdf_list()

    for pattern in std_id_glob_patterns(std_id):
        pattern_lower = pattern.lower()
        for hit in all_pdfs:
            if fnmatch.fnmatch(hit.name.lower(), pattern_lower):
                if filename_contains_std_id(hit.name, std_id):
                    key = str(hit.resolve()).lower()
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
        return str(path.resolve().relative_to(PDF_ROOT.resolve()))
    except ValueError:
        return path.name

