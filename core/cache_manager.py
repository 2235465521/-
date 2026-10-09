import json
import hashlib
import os
import sqlite3
import time
import threading
from pathlib import Path
from paths import DATA_DIR

DEFAULT_TTL = 3600
DEFAULT_COUNT_TTL = 7200

CACHE_DB_PATH = DATA_DIR / "query_cache.db"

class CacheManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._ensure_db()
        self._l1_cache: dict[str, tuple[dict, float, int]] = {}   # key -> (result, timestamp, ttl)
        self._l1_counts: dict[str, tuple[int, float, int]] = {}   # key -> (total, timestamp, ttl)
        self._mem_lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(CACHE_DB_PATH, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_db(self):
        os.makedirs(CACHE_DB_PATH.parent, exist_ok=True)
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    result TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS count_cache (
                    key TEXT PRIMARY KEY,
                    total INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )

    def make_cache_key(self, params: dict) -> str:
        # Deterministic key based on sorted JSON representation
        payload = json.dumps(params, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.md5(payload).hexdigest()

    def get_cached(self, key: str):
        now = time.time()
        # 1. Check in-memory L1 cache first
        with self._mem_lock:
            if key in self._l1_cache:
                res, created_at, ttl = self._l1_cache[key]
                if now - created_at < ttl:
                    return res
                else:
                    del self._l1_cache[key]

        # 2. Check SQLite L2 cache
        ttl = int(os.getenv("CACHE_TTL_SECONDS", str(DEFAULT_TTL)))
        try:
            with self._get_conn() as conn:
                cur = conn.execute(
                    "SELECT result, created_at FROM cache WHERE key = ?",
                    (key,)
                )
                row = cur.fetchone()
                if row:
                    result_json, created_at = row
                    if now - created_at < ttl:
                        data = json.loads(result_json)
                        with self._mem_lock:
                            if len(self._l1_cache) > 500:
                                self._l1_cache.clear()
                            self._l1_cache[key] = (data, created_at, ttl)
                        return data
        except Exception:
            pass
        return None

    def set_cached(self, key: str, result: dict, ttl: int | None = None):
        now = time.time()
        actual_ttl = ttl or int(os.getenv("CACHE_TTL_SECONDS", str(DEFAULT_TTL)))
        with self._mem_lock:
            if len(self._l1_cache) > 500:
                self._l1_cache.clear()
            self._l1_cache[key] = (result, now, actual_ttl)

        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, result, created_at) VALUES (?, ?, ?)",
                    (key, json.dumps(result, default=str), int(now))
                )
        except Exception:
            pass

    def get_cached_count(self, key: str) -> int | None:
        now = time.time()
        # 1. Check in-memory L1 count cache
        with self._mem_lock:
            if key in self._l1_counts:
                total, created_at, ttl = self._l1_counts[key]
                if now - created_at < ttl:
                    return total
                else:
                    del self._l1_counts[key]

        # 2. Check SQLite count_cache table
        ttl = int(os.getenv("CACHE_COUNT_TTL_SECONDS", str(DEFAULT_COUNT_TTL)))
        try:
            with self._get_conn() as conn:
                cur = conn.execute(
                    "SELECT total, created_at FROM count_cache WHERE key = ?",
                    (key,)
                )
                row = cur.fetchone()
                if row:
                    total, created_at = row
                    if now - created_at < ttl:
                        with self._mem_lock:
                            if len(self._l1_counts) > 500:
                                self._l1_counts.clear()
                            self._l1_counts[key] = (int(total), created_at, ttl)
                        return int(total)
        except Exception:
            pass
        return None

    def set_cached_count(self, key: str, total: int, ttl: int | None = None):
        now = time.time()
        actual_ttl = ttl or int(os.getenv("CACHE_COUNT_TTL_SECONDS", str(DEFAULT_COUNT_TTL)))
        with self._mem_lock:
            if len(self._l1_counts) > 500:
                self._l1_counts.clear()
            self._l1_counts[key] = (int(total), now, actual_ttl)

        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO count_cache (key, total, created_at) VALUES (?, ?, ?)",
                    (key, int(total), int(now))
                )
        except Exception:
            pass

    def clear_cache(self):
        with self._mem_lock:
            self._l1_cache.clear()
            self._l1_counts.clear()
        try:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM cache")
                conn.execute("DELETE FROM count_cache")
        except Exception:
            pass
