"""磁盘路径与分类目录（仅路径，不含服务端口等配置）。"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# ---------- 标准 PDF 根目录 ----------
# 库内 file_path 多为相对路径，如 国标下载/国标/xxx.pdf
_DEFAULT_PDF_ROOTS = [
    r"Y:\磁盘阵列\标准文件下载",
    r"E:\磁盘阵列\标准文件下载",
    r"Z:\磁盘阵列\标准文件下载",
    r"Z:\磁盘阵列\标准文件下载目录",
]

_STD_ROOT_MARKERS = (
    "国标下载",
    "行标下载",
    "地标下载",
    "企标下载",
    "团体标准",
)


def _resolve_pdf_root() -> Path:
    env_root = os.getenv("PDF_ROOT", "").strip()
    if env_root:
        return Path(env_root)

    candidates: list[Path] = [Path(p) for p in _DEFAULT_PDF_ROOTS]

    # 常见布局：与本项目同级的「国标下载 / 企标下载 …」所在目录
    parent = BASE_DIR.parent
    if any((parent / name).is_dir() for name in _STD_ROOT_MARKERS):
        candidates.insert(0, parent)

    for path in candidates:
        if path.is_dir():
            return path

    # 最后回退到项目内目录，并自动创建，避免「根目录不存在」阻断批量下载入口
    fallback = BASE_DIR / "data" / "pdf_files"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return fallback


PDF_ROOT = _resolve_pdf_root()

# ---------- 标准 PDF 搜索根目录 ----------
PDF_SEARCH_ROOT = Path(os.getenv("PDF_SEARCH_ROOT", str(PDF_ROOT.parent)))

# 标准库子目录显示名（文件夹名 → 短标签）
STD_FOLDER_LABELS: dict[str, str] = {
    "国标下载": "国标",
    "行标下载": "行标",
    "企标下载": "企标",
    "地标下载": "地标",
    "团体标准": "团体标准",
    "交通行业标准文件": "交通行业",
    "住建部标准": "住建部",
    "卫健委": "卫健委",
    "卫生标准文件": "卫生标准",
    "食品伙伴网": "食品伙伴网",
    "食品伙伴网团体标准数据": "食品伙伴团体标准",
}

STD_RESERVED_SLOTS: list[str] = [
    "（预留）其它标准库",
    "（预留）协会标准",
    "（预留）待扩展",
]

# ---------- 产品同类词库 ----------
PRODUCT_CLUSTERS_PATH = DATA_DIR / "product_clusters.json"

