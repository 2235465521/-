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
_DEFAULT_PDF_ROOTS = [
    r"Y:\磁盘阵列\标准文件下载",
    r"E:\磁盘阵列\标准文件下载",
    r"Z:\磁盘阵列\标准文件下载",
    r"Z:\磁盘阵列\标准文件下载目录",
]
_env_root = os.getenv("PDF_ROOT", "").strip()
if _env_root:
    PDF_ROOT = Path(_env_root)
else:
    PDF_ROOT = next(
        (Path(p) for p in _DEFAULT_PDF_ROOTS if Path(p).is_dir()),
        BASE_DIR / "data" / "pdf_files",
    )

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

