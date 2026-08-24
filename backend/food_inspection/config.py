"""项目全局配置，支持环境变量覆盖。"""

from __future__ import annotations

import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(ROOT_DIR)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(ROOT_DIR, "output"))


def _load_env_file(filename: str, *, override: bool = False) -> None:
    path = os.path.join(BACKEND_DIR, filename)
    if not os.path.isfile(path):
        path = os.path.join(ROOT_DIR, filename)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (override or key not in os.environ):
                os.environ[key] = value


_load_env_file(".env.mysql")
_mysql_profile = os.environ.get("MYSQL_PROFILE", "").strip()
if _mysql_profile:
    _load_env_file(f".env.mysql.{_mysql_profile}", override=True)

DATA_ROOT = os.environ.get("DATA_ROOT", r"Z:\全国各省市食品安全监督抽查")
CACHE_FILE = os.environ.get("CACHE_FILE", os.path.join(ROOT_DIR, "data_cache.json"))


def ensure_output_dir() -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR

APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = max(int(os.environ.get("APP_PORT", "8080")), 1)

_default_cors = "http://127.0.0.1:5173,http://localhost:5173"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", _default_cors).split(",")
    if origin.strip()
]

AUTO_SCAN_INTERVAL_SEC = max(int(os.environ.get("AUTO_SCAN_INTERVAL_SEC", "86400")), 60)
DISABLE_AUTO_SCAN = os.environ.get("DISABLE_AUTO_SCAN", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
PENDING_COUNT_TTL_SEC = max(int(os.environ.get("PENDING_COUNT_TTL_SEC", "600")), 60)

MYSQL_URL = os.environ.get("MYSQL_URL", "").strip()
IMPORT_FAILED_DIR = os.environ.get(
    "IMPORT_FAILED_DIR",
    os.path.join(DATA_ROOT, "import_failed_files"),
)
MYSQL_TABLE = os.environ.get("MYSQL_TABLE", "food_inspection_records")

_TESSERACT_CANDIDATES = (
    r"D:\xuexigongju\tesseract.exe",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)


def ensure_ocr_env() -> str | None:
    """为 PDF 扫描件 OCR 设置 TESSERACT_CMD（若尚未配置）。"""
    cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if cmd and os.path.isfile(cmd):
        return cmd
    for candidate in _TESSERACT_CANDIDATES:
        if os.path.isfile(candidate):
            os.environ["TESSERACT_CMD"] = candidate
            return candidate
    return None
