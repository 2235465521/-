"""制度文件：PDF / Word 按目录+文件名 FTS 索引。"""
from __future__ import annotations

from pathlib import Path

from paths import ZHIDU_DB_PATH, ZHIDU_DIR
from core.disk_catalog import DiskCatalog

ZHIDU_EXTENSIONS = frozenset({".pdf", ".doc", ".docx"})


def _parse_zhidu(path: Path, root: Path) -> dict | None:
    ext = path.suffix.lower()
    if ext not in ZHIDU_EXTENSIONS:
        return None
    rel = path.relative_to(root)
    category = rel.parent.as_posix() if rel.parent.parts else "根目录"
    if category == ".":
        category = "根目录"
    title = path.stem.strip() or path.name
    return {
        "filename": path.name,
        "category": category.replace("\\", "/"),
        "title": title,
        "rel_path": rel.as_posix(),
    }


zhidu = DiskCatalog(
    name="制度文件",
    root_dir=ZHIDU_DIR,
    db_path=ZHIDU_DB_PATH,
    table="zhidu_file",
    extensions=ZHIDU_EXTENSIONS,
    type_label="文件",
)
