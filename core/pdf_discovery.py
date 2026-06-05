"""在 PDF 目录中按标准号发现磁盘文件（数据库无 filepath 记录时使用）。"""

from __future__ import annotations

from pathlib import Path

from paths import PDF_ROOT, PDF_SEARCH_ROOT
from core.std_normalize import filename_contains_std_id, std_id_glob_patterns


def discover_pdfs_on_disk(std_id: str, limit: int = 20) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    for root in (PDF_ROOT, PDF_SEARCH_ROOT):
        if not root.is_dir():
            continue
        for pattern in std_id_glob_patterns(std_id):
            try:
                for hit in root.rglob(pattern):
                    if not hit.is_file():
                        continue
                    if not filename_contains_std_id(hit.name, std_id):
                        continue
                    key = str(hit.resolve()).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(hit)
                    if len(found) >= limit:
                        return sorted(found, key=lambda p: p.name)
            except OSError:
                continue

    return sorted(found, key=lambda p: p.name)


def pdf_display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PDF_ROOT.resolve()))
    except ValueError:
        return path.name
