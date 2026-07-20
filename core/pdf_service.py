"""PDF 路径解析与标准文件收集。"""
from __future__ import annotations

from pathlib import Path

from paths import PDF_ROOT, PDF_SEARCH_ROOT
from core.db import StandardInfo
from core.std_normalize import (
    db_filepath_matches_std,
    file_std_identity_key,
    filename_contains_std_id,
)


def find_pdf_on_disk(rel_path: str, file_name: str) -> Path | None:
    """按库内相对路径或文件名，在 PDF 根目录做轻量查找（不做全盘扫描）。"""
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    if rel:
        candidate = (PDF_ROOT / rel).resolve()
        if candidate.is_file():
            return candidate
    name = (file_name or "").strip()
    if name:
        for root in (PDF_ROOT, PDF_SEARCH_ROOT):
            if not root.is_dir():
                continue
            direct = root / name
            if direct.is_file():
                return direct
    return None


def _file_display_name(f: dict) -> str:
    name = (f.get("file_name") or "").strip()
    if name:
        return name
    rel = (f.get("file_path") or "").strip()
    return Path(rel.replace("\\", "/")).name if rel else ""


def _file_dedupe_key(f: dict) -> str:
    name = _file_display_name(f)
    identity = file_std_identity_key(name) if name else None
    if identity:
        return f"std:{identity}"
    resolved = (f.get("resolved_path") or "").strip().lower()
    if resolved:
        return f"path:{resolved}"
    rel = (f.get("file_path") or "").strip().lower().replace("\\", "/")
    if rel and name:
        return f"rel:{rel}|{name.lower()}"
    if name:
        return f"name:{name.lower()}"
    fid = f.get("id")
    return f"id:{fid}" if fid is not None else "anon"


def _file_preference_score(f: dict) -> tuple:
    """去重保留更优条目：磁盘存在 > 体积更小 > 有库内 id。"""
    size = int(f.get("file_size") or 0)
    return (
        1 if f.get("exists") else 0,
        1 if size > 0 else 0,
        -size if size > 0 else 0,
        1 if f.get("id") is not None else 0,
    )


def _append_unique_file(files: list[dict], seen: dict[str, int], entry: dict) -> None:
    key = _file_dedupe_key(entry)
    if key not in seen:
        seen[key] = len(files)
        files.append(entry)
        return
    idx = seen[key]
    if _file_preference_score(entry) > _file_preference_score(files[idx]):
        files[idx] = entry


def _db_file_matches_standard(std: StandardInfo, f: dict) -> bool:
    return db_filepath_matches_std(
        std.std_id or "",
        f.get("file_name"),
        f.get("file_path"),
    )


def collect_files_for_standard(std: StandardInfo) -> list[dict]:
    files: list[dict] = []
    seen: dict[str, int] = {}
    for f in std.files or []:
        if not _db_file_matches_standard(std, f):
            continue
        rel = f.get("file_path") or ""
        name = f.get("file_name") or ""
        found = find_pdf_on_disk(rel, name)
        if found and not filename_contains_std_id(found.name, std.std_id or ""):
            found = None
        entry = {
            **f,
            "exists": found is not None,
            "source": "db",
        }
        if found:
            entry["resolved_path"] = str(found)
            if not entry.get("file_size"):
                try:
                    entry["file_size"] = found.stat().st_size
                except OSError:
                    pass
        _append_unique_file(files, seen, entry)
    return files


def pick_pdf_path(std: StandardInfo, files: list[dict]) -> Path | None:
    for f in files:
        if not f.get("exists"):
            continue
        resolved = f.get("resolved_path")
        if resolved and Path(resolved).is_file():
            if filename_contains_std_id(Path(resolved).name, std.std_id or ""):
                return Path(resolved)
            continue
        found = find_pdf_on_disk(
            f.get("file_path") or "",
            f.get("file_name") or "",
        )
        if found and filename_contains_std_id(found.name, std.std_id or ""):
            return found
    return None
