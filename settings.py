"""应用运行参数（端口、数据库、缓存等，不含磁盘路径）。"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
OPEN_BROWSER = os.getenv("OPEN_BROWSER", "true").lower() in ("1", "true", "yes")

# 登录会话；未配置时写入 data/.flask_secret 并复用
ALLOW_REGISTER = os.getenv("ALLOW_REGISTER", "true").lower() in ("1", "true", "yes")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))


def _resolve_secret_key() -> str:
    env_key = (os.getenv("SECRET_KEY") or "").strip()
    if env_key:
        return env_key
    secret_path = Path(__file__).resolve().parent / "data" / ".flask_secret"
    try:
        if secret_path.is_file():
            saved = secret_path.read_text(encoding="utf-8").strip()
            if saved:
                return saved
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_hex(32)
        secret_path.write_text(generated, encoding="utf-8")
        return generated
    except OSError:
        return secrets.token_hex(32)


SECRET_KEY = _resolve_secret_key()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "mydate")
DB_BACKEND = os.getenv("DB_BACKEND", "auto").lower()

CACHE_VERSION = os.getenv("CACHE_VERSION", "2.3.0")
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
CACHE_MAX_MEMORY = int(os.getenv("CACHE_MAX_MEMORY", "800"))
CACHE_TTL_SEARCH = int(os.getenv("CACHE_TTL_SEARCH", "1800"))
CACHE_TTL_SUGGEST = int(os.getenv("CACHE_TTL_SUGGEST", "600"))
CACHE_TTL_DETAIL = int(os.getenv("CACHE_TTL_DETAIL", "7200"))
CACHE_TTL_DISK = int(os.getenv("CACHE_TTL_DISK", "86400"))

ES_ENABLED = os.getenv("ES_ENABLED", "auto").lower()
ES_SCHEME = os.getenv("ES_SCHEME", "http")
ES_HOST = os.getenv("ES_HOST", "127.0.0.1")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
ES_INDEX = os.getenv("ES_INDEX", "standards")
ES_USER = os.getenv("ES_USER", "")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")

APP_VERSION = "3.0.0"

# 智谱 AI（自然语言检索）
ZHIPU_API_KEY = (os.getenv("ZHIPU_API_KEY") or "").strip()
ZHIPU_API_BASE = os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
ZHIPU_MODEL = os.getenv("ZHIPU_MODEL", "glm-4-flash")
