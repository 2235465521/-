"""应用运行参数（端口、数据库、缓存等，不含磁盘路径）。"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
OPEN_BROWSER = os.getenv("OPEN_BROWSER", "true").lower() in ("1", "true", "yes")

MYSQL_HOST = os.getenv("MYSQL_HOST", "192.168.10.225")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "zkbz2025")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "STSC_standard_database")
DB_BACKEND = os.getenv("DB_BACKEND", "auto").lower()

CACHE_VERSION = os.getenv("CACHE_VERSION", "2.3.0")
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
CACHE_MAX_MEMORY = int(os.getenv("CACHE_MAX_MEMORY", "800"))
CACHE_TTL_SEARCH = int(os.getenv("CACHE_TTL_SEARCH", "1800"))
CACHE_TTL_SUGGEST = int(os.getenv("CACHE_TTL_SUGGEST", "600"))
CACHE_TTL_DETAIL = int(os.getenv("CACHE_TTL_DETAIL", "7200"))
CACHE_TTL_DISK = int(os.getenv("CACHE_TTL_DISK", "86400"))

# 中文复合词扩展召回（储能预制舱 → 储能 + 预制舱），关闭后回到整词精确匹配
SEARCH_EXPAND_QUERY = os.getenv("SEARCH_EXPAND_QUERY", "true").lower() in ("1", "true", "yes")

# ngram 全文索引召回（需先执行 scripts/ngram_fulltext.sql 在 std_base 上建索引）。
# 默认关闭：不建索引时与原有 LIKE 行为完全一致；上线 ngram 后设为 1 启用。
SEARCH_USE_NGRAM = os.getenv("SEARCH_USE_NGRAM", "0").lower() in ("1", "true", "yes")

ES_ENABLED = os.getenv("ES_ENABLED", "auto").lower()
ES_SCHEME = os.getenv("ES_SCHEME", "http")
ES_HOST = os.getenv("ES_HOST", "127.0.0.1")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
ES_INDEX = os.getenv("ES_INDEX", "standards")
ES_USER = os.getenv("ES_USER", "")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")

APP_VERSION = "3.0.0"
