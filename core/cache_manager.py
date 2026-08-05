import json
import hashlib
import os
import sqlite3
import time
from pathlib import Path

# Default TTL (seconds) for cache entries; can be overridden via env var CACHE_TTL_SECONDS
DEFAULT_TTL = 3600
from paths import DATA_DIR

CACHE_DB_PATH = DATA_DIR / "query_cache.db"

class CacheManager:
    def __init__(self):
        self._ensure_db()

    def _ensure_db(self):
        os.makedirs(CACHE_DB_PATH.parent, exist_ok=True)
        conn = sqlite3.connect(CACHE_DB_PATH)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                result TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

    def make_cache_key(self, params: dict) -> str:
        # Deterministic key based on sorted JSON representation
        payload = json.dumps(params, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.md5(payload).hexdigest()

    def get_cached(self, key: str):
        ttl = int(os.getenv("CACHE_TTL_SECONDS", str(DEFAULT_TTL)))
        conn = sqlite3.connect(CACHE_DB_PATH)
        cur = conn.execute(
            "SELECT result, created_at FROM cache WHERE key = ?",
            (key,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            result_json, created_at = row
            if time.time() - created_at < ttl:
                return json.loads(result_json)
        return None

    def set_cached(self, key: str, result: dict):
        ttl = int(os.getenv("CACHE_TTL_SECONDS", str(DEFAULT_TTL)))
        # Store regardless; cleanup occurs on reads based on TTL
        conn = sqlite3.connect(CACHE_DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, result, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(result, default=str), int(time.time()))
        )
        conn.commit()
        conn.close()

    def clear_cache(self):
        conn = sqlite3.connect(CACHE_DB_PATH)
        conn.execute("DELETE FROM cache")
        conn.commit()
        conn.close()
