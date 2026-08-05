"""PDF 路径解析与标准文件收集。"""
from __future__ import annotations
import re

from pathlib import Path

from paths import PDF_ROOT, PDF_SEARCH_ROOT
from core.db import StandardInfo
from core.pdf_discovery import (
    discover_pdfs_on_disk,
    pdf_display_path,
    find_pdf_by_filename_on_disk,
    check_file_exists_in_cache,
)


def find_pdf_on_disk(
    rel_path: str,
    file_name: str,
    *,
    std_id: str | None = None,
    scan_disk: bool = True,
) -> Path | None:
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    if rel:
        candidate = PDF_ROOT / rel
        try:
            if check_file_exists_in_cache(candidate):
                return candidate
        except Exception:
            pass
    name = (file_name or "").strip()
    if name:
        # 1. 尝试直接路径匹配（直接寻找，不遍历，最快）
        for root in (PDF_ROOT, PDF_SEARCH_ROOT):
            if not root.is_dir():
                continue
            direct = root / name
            try:
                if check_file_exists_in_cache(direct):
                    return direct
            except Exception:
                pass
        
        # 2. 如果直接路径找不到，且允许扫盘，在缓存的磁盘 PDF 列表中快速查找
        if scan_disk:
            found = find_pdf_by_filename_on_disk(name)
            if found:
                return found

    if std_id and scan_disk:
        hits = discover_pdfs_on_disk(std_id, limit=5)
        if hits:
            return hits[0]
    return None


def _file_dedupe_key(f: dict) -> str:
    resolved = (f.get("resolved_path") or "").strip().lower()
    if resolved:
        return f"path:{resolved}"
    rel = (f.get("file_path") or "").strip().lower().replace("\\", "/")
    name = (f.get("file_name") or "").strip().lower()
    if rel and name:
        return f"rel:{rel}|{name}"
    if name:
        return f"name:{name}"
    fid = f.get("id")
    return f"id:{fid}" if fid is not None else f"disk:{f.get('disk_index', 0)}"


def _append_unique_file(files: list[dict], seen: set[str], entry: dict) -> None:
    key = _file_dedupe_key(entry)
    if key in seen:
        return
    seen.add(key)
    files.append(entry)


def collect_files_for_standard(std: StandardInfo, *, scan_disk: bool = True) -> list[dict]:
    # Helper to verify that a PDF filename matches the standard ID
    def _std_id_matches_filename(std_id: str, filename: str) -> bool:
        """Return True if normalized std_id appears in normalized filename.
        Normalization removes non‑alphanumeric characters and lower‑cases both strings.
        """
        std_norm = re.sub(r"[^0-9a-zA-Z]", "", std_id).lower()
        file_norm = re.sub(r"[^0-9a-zA-Z]", "", filename).lower()
        if std_norm in file_norm:
            return True
        # Relaxed matching (strip optional T/Z/X from prefix like DB12T -> DB12, GBT -> GB)
        std_relaxed = re.sub(r"^([a-z]{2,5}\d{0,2})[tzx]", r"\1", std_norm)
        file_relaxed = re.sub(r"^([a-z]{2,5}\d{0,2})[tzx]", r"\1", file_norm)
        if std_relaxed in file_relaxed:
            return True
        return False
    files: list[dict] = []
    # Helper to pick the optimal PDF among duplicates
    def _select_best_file(candidates: list[dict]) -> list[dict]:
        """Return a list containing the best PDF file.
        Preference order:
          1. Source 'db' with exists=True
          2. Source 'disk' with exists=True
          3. Any file with exists=True
        If none exist, return empty list.
        """
        best = None
        for f in candidates:
            if not f.get("exists"):
                continue
            src = f.get("source")
            if src == "db":
                return [f]
            if best is None and src == "disk":
                best = f
        if best:
            return [best]
        # fallback: first existing file
        for f in candidates:
            if f.get("exists"):
                return [f]
        return []

    seen: set[str] = set()
    for f in std.files or []:
        rel = f.get("file_path") or ""
        name = f.get("file_name") or ""
        # 1. 预先校验：若数据库文件记录的名称与当前标准号年份不匹配，则直接忽略此记录（年份不一样的不要展示）
        if not _std_id_matches_filename(std.std_id, name):
            continue
        # 2. 传入 std_id=None，避免在循环体内重复执行昂贵的多模板扫盘
        found = find_pdf_on_disk(rel, name, std_id=None, scan_disk=scan_disk)
        if found:
            entry = {
                **f,
                "exists": True,
                "source": "db",
                "resolved_path": str(found),
            }
            _append_unique_file(files, seen, entry)
    # 3. 只有当数据库匹配记录为空或均失效时，才执行兜底磁盘扫盘
    if scan_disk and not any(x.get("exists") for x in files):
        for i, pdf in enumerate(discover_pdfs_on_disk(std.std_id, limit=10)):
            # Ensure the discovered PDF filename matches the standard ID
            if not _std_id_matches_filename(std.std_id, pdf.name):
                continue
            try:
                rel = pdf_display_path(pdf)
            except Exception:
                rel = pdf.name
            _append_unique_file(
                files,
                seen,
                {
                    "id": None,
                    "file_name": pdf.name,
                    "file_path": rel,
                    "exists": True,
                    "source": "disk",
                    "disk_index": i,
                    "resolved_path": str(pdf),
                },
            )
    return _select_best_file(files)


def pick_pdf_path(std: StandardInfo, files: list[dict], *, scan_disk: bool = True) -> Path | None:
    for f in files:
        if not f.get("exists"):
            continue
        resolved = f.get("resolved_path")
        if resolved and check_file_exists_in_cache(Path(resolved)):
            return Path(resolved)
        found = find_pdf_on_disk(
            f.get("file_path") or "",
            f.get("file_name") or "",
            std_id=std.std_id,
            scan_disk=scan_disk,
        )
        if found:
            return found
    return None
