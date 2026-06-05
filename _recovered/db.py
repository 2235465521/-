from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import pymysql

from config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    SQLITE_PATH,
)

EX_STATE_LABEL = {0: "废止", 1: "现行", 2: "即将实施"}


@dataclass
class StandardInfo:
    id: int
    std_id: str
    std_type: str | None
    std_chinesename: str | None
    std_status: str | None
    ex_state: int | None
    ex_state_label: str
    release_date: str | None
    implement_date: str | None
    files: list[dict]


def normalize_std_id(std_id: str) -> str:
    s = std_id.strip().upper()
    s = re.sub(r"\s+", "", s)
    s = s.replace("／", "/")
    return s


def _row_to_standard(row: dict, files: list[dict]) -> StandardInfo:
    ex = row.get("ex_state")
    return StandardInfo(
        id=row["id"],
        std_id=row["std_id"],
        std_type=row.get("std_type"),
        std_chinesename=row.get("std_chinesename"),
        std_status=row.get("std_status"),
        ex_state=ex,
        ex_state_label=EX_STATE_LABEL.get(ex, row.get("std_status") or "未知"),
        release_date=str(row["release_date"]) if row.get("release_date") else None,
        implement_date=str(row["implement_date"])
        if row.get("implement_date")
        else None,
        files=files,
    )


class Database:
    def __init__(self) -> None:
        self._mysql_ok: bool | None = None

    def _mysql_available(self) -> bool:
        if self._mysql_ok is not None:
            return self._mysql_ok
        if not MYSQL_PASSWORD:
            self._mysql_ok = False
            return False
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                charset="utf8mb4",
                connect_timeout=3,
            )
            conn.close()
            self._mysql_ok = True
        except Exception:
            self._mysql_ok = False
        return self._mysql_ok

    @contextmanager
    def _mysql(self):
        conn = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _sqlite(self):
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def backend_name(self) -> str:
        if self._mysql_available():
            return "MySQL"
        if SQLITE_PATH.is_file():
            return "SQLite"
        return "未就绪"

    def is_ready(self) -> bool:
        return self._mysql_available() or SQLITE_PATH.is_file()

    def _fetch_files_mysql(self, cur, base_id: int) -> list[dict]:
        cur.execute(
            """
            SELECT id, file_path, file_name, file_size
            FROM std_filepath WHERE base_id = %s
            ORDER BY file_name
            """,
            (base_id,),
        )
        return list(cur.fetchall())

    def _fetch_files_sqlite(self, conn, base_id: int) -> list[dict]:
        cur = conn.execute(
            """
            SELECT id, file_path, file_name, file_size
            FROM std_filepath WHERE base_id = ?
            ORDER BY file_name
            """,
            (base_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def search(self, query: str, limit: int = 20) -> list[StandardInfo]:
        q = query.strip()
        if not q:
            return []
        norm = normalize_std_id(q)

        if self._mysql_available():
            return self._search_mysql(q, norm, limit)
        return self._search_sqlite(q, norm, limit)

    def _search_mysql(self, q: str, norm: str, limit: int) -> list[StandardInfo]:
        results: list[StandardInfo] = []
        seen: set[int] = set()
        with self._mysql() as conn:
            cur = conn.cursor()
            for sql, params in (
                (
                    "SELECT * FROM std_base WHERE std_id = %s LIMIT %s",
                    (q, limit),
                ),
                (
                    "SELECT * FROM std_base WHERE REPLACE(UPPER(std_id),' ','') = %s LIMIT %s",
                    (norm, limit),
                ),
                (
                    "SELECT * FROM std_base WHERE std_id LIKE %s LIMIT %s",
                    (f"%{q}%", limit),
                ),
            ):
                cur.execute(sql, params)
                for row in cur.fetchall():
                    bid = row["id"]
                    if bid in seen:
                        continue
                    seen.add(bid)
                    files = self._fetch_files_mysql(cur, bid)
                    results.append(_row_to_standard(row, files))
                    if len(results) >= limit:
                        return results
        return results

    def _search_sqlite(self, q: str, norm: str, limit: int) -> list[StandardInfo]:
        if not SQLITE_PATH.is_file():
            return []
        results: list[StandardInfo] = []
        seen: set[int] = set()
        with self._sqlite() as conn:
            for sql, params in (
                ("SELECT * FROM std_base WHERE std_id = ? LIMIT ?", (q, limit)),
                (
                    "SELECT * FROM std_base WHERE std_id_norm = ? LIMIT ?",
                    (norm, limit),
                ),
                (
                    "SELECT * FROM std_base WHERE std_id LIKE ? LIMIT ?",
                    (f"%{q}%", limit),
                ),
            ):
                cur = conn.execute(sql, params)
                for row in cur.fetchall():
                    d = dict(row)
                    bid = d["id"]
                    if bid in seen:
                        continue
                    seen.add(bid)
                    files = self._fetch_files_sqlite(conn, bid)
                    results.append(_row_to_standard(d, files))
                    if len(results) >= limit:
                        return results
        return results

    def get_by_id(self, base_id: int) -> StandardInfo | None:
        if self._mysql_available():
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM std_base WHERE id = %s", (base_id,))
                row = cur.fetchone()
                if not row:
                    return None
                files = self._fetch_files_mysql(cur, base_id)
                return _row_to_standard(row, files)
        if not SQLITE_PATH.is_file():
            return None
        with self._sqlite() as conn:
            cur = conn.execute("SELECT * FROM std_base WHERE id = ?", (base_id,))
            row = cur.fetchone()
            if not row:
                return None
            files = self._fetch_files_sqlite(conn, base_id)
            return _row_to_standard(dict(row), files)

    def get_filepath_record(self, file_id: int) -> dict | None:
        if self._mysql_available():
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, base_id, file_path, file_name FROM std_filepath WHERE id = %s",
                    (file_id,),
                )
                return cur.fetchone()
        if not SQLITE_PATH.is_file():
            return None
        with self._sqlite() as conn:
            cur = conn.execute(
                "SELECT id, base_id, file_path, file_name FROM std_filepath WHERE id = ?",
                (file_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


db = Database()
