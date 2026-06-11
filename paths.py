"""磁盘路径与分类目录（仅路径，不含服务端口等配置）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 环境变量（确保在其他文件导入路径前已载入配置）
load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# 判断当前系统是否为 Windows
IS_WINDOWS = sys.platform.startswith("win")

# ---------- 标准 PDF 根目录 ----------
_DEFAULT_PDF_ROOTS = [
    r"Y:\磁盘阵列\标准文件下载",
    r"E:\标准文件下载",
    r"E:\磁盘阵列\标准文件下载",
    r"Z:\磁盘阵列\标准文件下载",
    r"Z:\磁盘阵列\标准文件下载目录",
]
_env_root = os.getenv("PDF_ROOT", "").strip()
if _env_root:
    PDF_ROOT = Path(_env_root)
else:
    if IS_WINDOWS:
        PDF_ROOT = next(
            (Path(p) for p in _DEFAULT_PDF_ROOTS if Path(p).is_dir()),
            DATA_DIR / "pdf",
        )
    else:
        PDF_ROOT = DATA_DIR / "pdf"

# ---------- 标准扫描根目录 ----------
_DEFAULT_PDF_SEARCH_ROOTS = [
    r"Y:\磁盘阵列",
    r"E:\磁盘阵列",
]
_env_search_root = os.getenv("PDF_SEARCH_ROOT", "").strip()
if _env_search_root:
    PDF_SEARCH_ROOT = Path(_env_search_root)
else:
    if IS_WINDOWS:
        PDF_SEARCH_ROOT = next(
            (Path(p) for p in _DEFAULT_PDF_SEARCH_ROOTS if Path(p).is_dir()),
            PDF_ROOT,
        )
    else:
        PDF_SEARCH_ROOT = PDF_ROOT

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


def _first_existing_dir(candidates: list[str], fallback: str) -> Path:
    for p in candidates:
        path = Path(p)
        if path.is_dir():
            return path
    return Path(fallback)


# ---------- 团标征求意见稿 ----------
_DEFAULT_TUANGBIAO_DIRS = [
    str(PDF_ROOT / "团体标准" / "团标征求意见稿下载"),
    r"Z:\磁盘阵列\标准文件下载\团体标准\团标征求意见稿下载",
    r"E:\磁盘阵列\标准文件下载\团体标准\团标征求意见稿下载",
]
_env_tuangbiao = os.getenv("TUANGBIAO_DIR", "").strip()
if _env_tuangbiao:
    TUANGBIAO_DIR = Path(_env_tuangbiao)
else:
    if IS_WINDOWS:
        TUANGBIAO_DIR = _first_existing_dir(_DEFAULT_TUANGBIAO_DIRS, _DEFAULT_TUANGBIAO_DIRS[0])
    else:
        TUANGBIAO_DIR = PDF_ROOT / "团体标准" / "团标征求意见稿下载"

# ---------- 制度文件根目录 ----------
_DEFAULT_ZHIDU_DIRS = [
    r"Y:\磁盘阵列\制度文件",
    r"Z:\磁盘阵列\制度文件",
    r"E:\磁盘阵列\制度文件",
]
_env_zhidu = os.getenv("ZHIDU_DIR", "").strip()
if _env_zhidu:
    ZHIDU_ROOT = Path(_env_zhidu)
else:
    if IS_WINDOWS:
        ZHIDU_ROOT = _first_existing_dir(_DEFAULT_ZHIDU_DIRS, _DEFAULT_ZHIDU_DIRS[0])
    else:
        ZHIDU_ROOT = DATA_DIR / "zhidu"
# 兼容旧名
ZHIDU_DIR = ZHIDU_ROOT
ZHIDU_RESERVED_SLOTS: list[str] = [
    "（预留）新协会制度",
    "（预留）地方制度",
    "（预留）待扩展",
]

# ---------- 本地索引库路径 ----------
SQLITE_PATH = DATA_DIR / "standards.db"
CACHE_DB_PATH = DATA_DIR / "query_cache.db"
TUANGBIAO_DB_PATH = DATA_DIR / "tuangbiao.db"
ZHIDU_DB_PATH = DATA_DIR / "zhidu.db"
UNITS_DB_PATH = DATA_DIR / "units.db"

# ---------- SQL 导出（构建索引） ----------
_env_sql_dump = os.getenv("SQL_DUMP_DIR", "").strip()
if _env_sql_dump:
    SQL_DUMP_DIR = Path(_env_sql_dump)
else:
    if IS_WINDOWS:
        SQL_DUMP_DIR = Path(r"C:\Users\20711\Desktop\mydate")
    else:
        SQL_DUMP_DIR = DATA_DIR / "mydate"

# ---------- 产品同类词库 ----------
PRODUCT_CLUSTERS_PATH = DATA_DIR / "product_clusters.json"
