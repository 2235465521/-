"""团标征求意见稿：按文件名 FTS 索引。"""
from __future__ import annotations

from pathlib import Path

from paths import TUANGBIAO_DB_PATH, TUANGBIAO_DIR
from core.disk_catalog import DiskCatalog


def _parse_tuangbiao(path: Path, root: Path) -> dict | None:
    name = path.name
    if not name.lower().endswith(".pdf"):
        return None
    stem = path.stem
    if "_" in stem:
        org, title = stem.split("_", 1)
        org = org.strip() or "未知协会"
        title = title.strip() or stem
    else:
        org = "团标"
        title = stem
    return {
        "filename": name,
        "category": org,
        "title": title,
        "rel_path": str(path.relative_to(root)).replace("\\", "/"),
    }


tuangbiao = DiskCatalog(
    name="团标征求意见稿",
    root_dir=TUANGBIAO_DIR,
    db_path=TUANGBIAO_DB_PATH,
    table="tuangbiao_file",
    extensions=frozenset({".pdf"}),
    type_label="PDF",
)
