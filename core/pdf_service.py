"""PDF 路径解析与标准文件收集。"""
from __future__ import annotations

from pathlib import Path

from paths import PDF_ROOT, PDF_SEARCH_ROOT
from core.db import StandardInfo
from core.pdf_discovery import (
    discover_pdfs_on_disk,
    pdf_display_path,
    find_pdf_by_filename_on_disk,
    check_file_exists_in_cache,
)
from core.std_normalize import filename_contains_std_id


def _basename_equals(a: str, b: str) -> bool:
    return Path(a or "").name.lower() == Path(b or "").name.lower()


def _path_matches_expected(
    path: Path,
    *,
    file_name: str | None = None,
    std_id: str | None = None,
) -> bool:
    """解析到的磁盘文件必须与期望文件名 / 标准号一致，避免 file_path 错指。"""
    name = (file_name or "").strip()
    if name and not _basename_equals(path.name, name):
        return False
    if std_id and not filename_contains_std_id(path.name, std_id):
        return False
    return True


def find_pdf_on_disk(
    rel_path: str,
    file_name: str,
    *,
    std_id: str | None = None,
    scan_disk: bool = True,
) -> Path | None:
    """按 file_path → file_name → 标准号扫盘 依次查找，并校验文件名与标准号一致。"""
    name = (file_name or "").strip()
    rel = (rel_path or "").replace("\\", "/").lstrip("/")

    # 1. 数据库相对路径：仅当实际 basename 与 file_name / std_id 一致时才采用
    if rel:
        candidate = PDF_ROOT / rel
        try:
            if check_file_exists_in_cache(candidate) and _path_matches_expected(
                candidate, file_name=name or None, std_id=std_id
            ):
                return candidate
        except Exception:
            pass

    # 2. 按 file_name 精确查找（路径错指时的正确回退）
    if name:
        for root in (PDF_ROOT, PDF_SEARCH_ROOT):
            if not root.is_dir():
                continue
            direct = root / name
            try:
                if check_file_exists_in_cache(direct) and _path_matches_expected(
                    direct, file_name=name, std_id=std_id
                ):
                    return direct
            except Exception:
                pass

        if scan_disk:
            found = find_pdf_by_filename_on_disk(name)
            if found and _path_matches_expected(found, file_name=name, std_id=std_id):
                return found

    # 3. 按标准号在磁盘缓存中兜底
    if std_id and scan_disk:
        hits = discover_pdfs_on_disk(std_id, limit=5)
        for hit in hits:
            if filename_contains_std_id(hit.name, std_id):
                return hit
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
    for f in candidates:
        if f.get("exists"):
            return [f]
    return []


def collect_files_for_standard(std: StandardInfo, *, scan_disk: bool = True) -> list[dict]:
    files: list[dict] = []
    seen: set[str] = set()
    for f in std.files or []:
        rel = f.get("file_path") or ""
        db_name = (f.get("file_name") or "").strip()
        # file_name 仅在含本标准号时参与精确匹配；否则忽略，避免错名把解析带偏
        name = (
            db_name
            if db_name and filename_contains_std_id(db_name, std.std_id)
            else ""
        )
        # 解析时强制校验 std_id：拒绝 file_path 指向其它标准 PDF 的错配
        found = find_pdf_on_disk(rel, name, std_id=std.std_id, scan_disk=False)
        if not found and scan_disk:
            found = find_pdf_on_disk(rel, name, std_id=std.std_id, scan_disk=True)
        if not found:
            continue
        if not filename_contains_std_id(found.name, std.std_id):
            continue
        entry = {
            **f,
            # 展示名与真实文件一致，避免题目显示 A、内容却是 B
            "file_name": found.name,
            "exists": True,
            "source": "db",
            "resolved_path": str(found),
        }
        _append_unique_file(files, seen, entry)

    # 4. 仅当库记录均未命中时，才按标准号扫盘兜底
    if scan_disk and not any(x.get("exists") for x in files):
        for i, pdf in enumerate(discover_pdfs_on_disk(std.std_id, limit=10)):
            if not filename_contains_std_id(pdf.name, std.std_id):
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
        if resolved:
            path = Path(resolved)
            if check_file_exists_in_cache(path) and filename_contains_std_id(
                path.name, std.std_id
            ):
                return path
        found = find_pdf_on_disk(
            f.get("file_path") or "",
            f.get("file_name") or "",
            std_id=std.std_id,
            scan_disk=scan_disk,
        )
        if found and filename_contains_std_id(found.name, std.std_id):
            return found
    return None
