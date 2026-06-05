import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = DATA_DIR / "standards.db"

# PDF 根目录：数据库 file_path 为相对路径（如 国标下载/国标/xxx.pdf）
PDF_ROOT = Path(
    os.getenv(
        "PDF_ROOT",
        r"Z:\磁盘阵列\标准文件下载目录",
    )
)

# MySQL（可选；配置后优先使用，未配置或连接失败则使用 SQLite）
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "mydate")

# SQL 导出目录（用于 build_index.py 从桌面 mydate 构建 SQLite）
SQL_DUMP_DIR = Path(
    os.getenv(
        "SQL_DUMP_DIR",
        r"C:\Users\20711\Desktop\mydate",
    )
)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
