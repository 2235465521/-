"""项目全局配置，支持环境变量覆盖。"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(ROOT_DIR)


def _load_deploy_env() -> None:
    """加载 deploy.env（或 DEPLOY_ENV_FILE 指定文件），已存在的环境变量不会被覆盖。"""
    env_file = os.environ.get(
        "DEPLOY_ENV_FILE",
        os.path.join(PROJECT_DIR, "deploy.env"),
    )
    if not os.path.isfile(env_file):
        return
    with open(env_file, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_deploy_env()


def _load_mysql_env() -> None:
    """加载 backend/.env.mysql（已存在的环境变量不会被覆盖）。"""
    env_file = os.path.join(ROOT_DIR, ".env.mysql")
    if not os.path.isfile(env_file):
        return
    with open(env_file, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_mysql_env()

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(ROOT_DIR, "output"))

if sys.platform == "win32":
    _DEFAULT_DATA_ROOT = r"Z:\全国各省市食品安全监督抽查"
else:
    _DEFAULT_DATA_ROOT = "/mnt/std_bk/全国各省市食品安全监督抽查"

DATA_ROOT = os.environ.get("DATA_ROOT", _DEFAULT_DATA_ROOT)
CACHE_FILE = os.environ.get("CACHE_FILE", os.path.join(ROOT_DIR, "data_cache.json"))
STATIC_DIR = os.environ.get(
    "STATIC_DIR",
    os.path.join(PROJECT_DIR, "frontend", "dist"),
)


def ensure_output_dir() -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


PRODUCTION = _env_flag("PRODUCTION")
SERVE_STATIC = PRODUCTION or _env_flag("SERVE_STATIC")

if sys.platform == "win32":
    _DEFAULT_APP_HOST = "127.0.0.1"
else:
    _DEFAULT_APP_HOST = "0.0.0.0"

APP_HOST = os.environ.get("APP_HOST", _DEFAULT_APP_HOST)
APP_PORT = max(int(os.environ.get("APP_PORT", "8080")), 1)

if "CORS_ORIGINS" in os.environ:
    _cors_raw = os.environ["CORS_ORIGINS"]
elif SERVE_STATIC:
    _cors_raw = ""
else:
    _cors_raw = "http://127.0.0.1:5173,http://localhost:5173"

CORS_ORIGINS = [origin.strip() for origin in _cors_raw.split(",") if origin.strip()]

AUTO_SCAN_INTERVAL_SEC = max(int(os.environ.get("AUTO_SCAN_INTERVAL_SEC", "86400")), 60)
DISABLE_AUTO_SCAN = os.environ.get("DISABLE_AUTO_SCAN", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
PENDING_COUNT_TTL_SEC = max(int(os.environ.get("PENDING_COUNT_TTL_SEC", "600")), 60)

USE_MYSQL = _env_flag("USE_MYSQL")
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = max(int(os.environ.get("MYSQL_PORT", "3306")), 1)
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "zkbz2025")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "shipin1")
MYSQL_TABLE = os.environ.get("MYSQL_TABLE", "fact_food_inspection")

_default_mysql_url = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4" if (USE_MYSQL or MYSQL_PASSWORD or MYSQL_USER) else ""
MYSQL_URL = os.environ.get("MYSQL_URL", "").strip() or _default_mysql_url

