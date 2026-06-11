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
from core.search_query import (
    build_keyword_match_clause,
    keyword_match_order_by,
    mysql_keyword_match_order_by,
)
from core.std_normalize import normalize_std_id, std_id_compact_key, std_id_norm_key

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
        norm = std_id_norm_key(q)
        compact = std_id_compact_key(q)

        if self._mysql_available():
            return self._search_mysql(q, norm, compact, limit)
        return self._search_sqlite(q, norm, compact, limit)

    def _search_mysql(
        self, q: str, norm: str, compact: str, limit: int
    ) -> list[StandardInfo]:
        results: list[StandardInfo] = []
        seen: set[int] = set()
        std_compact = (
            "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(UPPER(std_id),' ',''),'/',''),"
            "'-',''),'—',''),'－','')"
        )
        with self._mysql() as conn:
            cur = conn.cursor()
            from core.std_normalize import std_id_lookup_variants

            attempts: list[tuple[str, tuple]] = []
            for variant in std_id_lookup_variants(q):
                attempts.append(
                    ("SELECT * FROM std_base WHERE std_id = %s LIMIT %s", (variant, limit))
                )
                attempts.append(
                    (
                        "SELECT * FROM std_base WHERE REPLACE(UPPER(std_id),' ','') = %s LIMIT %s",
                        (std_id_norm_key(variant), limit),
                    )
                )
                attempts.append(
                    (f"SELECT * FROM std_base WHERE {std_compact} = %s LIMIT %s", (std_id_compact_key(variant), limit))
                )
            attempts.extend(
                [
                    ("SELECT * FROM std_base WHERE std_id = %s LIMIT %s", (q, limit)),
                    (
                        "SELECT * FROM std_base WHERE REPLACE(UPPER(std_id),' ','') = %s LIMIT %s",
                        (norm, limit),
                    ),
                    (f"SELECT * FROM std_base WHERE {std_compact} = %s LIMIT %s", (compact, limit)),
                    (
                        "SELECT * FROM std_base WHERE UPPER(std_id) LIKE %s LIMIT %s",
                        (f"%{q.strip().upper()}%", limit),
                    ),
                ]
            )
            for sql, params in attempts:
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

    def _search_sqlite(
        self, q: str, norm: str, compact: str, limit: int
    ) -> list[StandardInfo]:
        if not SQLITE_PATH.is_file():
            return []
        from core.std_normalize import std_id_lookup_variants

        results: list[StandardInfo] = []
        seen: set[int] = set()
        with self._sqlite() as conn:
            attempts: list[tuple[str, tuple]] = []
            for variant in std_id_lookup_variants(q):
                attempts.append(
                    (
                        "SELECT * FROM std_base WHERE std_id = ? OR std_id_norm = ? LIMIT ?",
                        (variant, std_id_norm_key(variant), limit),
                    )
                )
            attempts.extend(
                [
                    ("SELECT * FROM std_base WHERE std_id = ? LIMIT ?", (q, limit)),
                    (
                        "SELECT * FROM std_base WHERE std_id_norm = ? LIMIT ?",
                        (norm, limit),
                    ),
                    (
                        "SELECT * FROM std_base WHERE std_id_norm = ? LIMIT ?",
                        (compact, limit),
                    ),
                    (
                        "SELECT * FROM std_base WHERE UPPER(std_id) LIKE ? LIMIT ?",
                        (f"%{q.strip().upper()}%", limit),
                    ),
                ]
            )
            for sql, params in attempts:
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

    def search_std_id(self, query: str) -> StandardInfo | None:
        """仅按标准号精确/变体匹配（批量下载用，不用名称模糊）。"""
        q = (query or "").strip()
        if not q:
            return None
        norm = std_id_norm_key(q)
        compact = std_id_compact_key(q)
        from core.std_normalize import std_id_lookup_variants

        if self._mysql_available():
            std_compact = (
                "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(UPPER(std_id),' ',''),'/',''),"
                "'-',''),'—',''),'－','')"
            )
            with self._mysql() as conn:
                cur = conn.cursor()
                for variant in std_id_lookup_variants(q):
                    cur.execute(
                        "SELECT * FROM std_base WHERE std_id = %s LIMIT 1",
                        (variant,),
                    )
                    row = cur.fetchone()
                    if row:
                        files = self._fetch_files_mysql(cur, row["id"])
                        return _row_to_standard(row, files)
                    cur.execute(
                        "SELECT * FROM std_base WHERE REPLACE(UPPER(std_id),' ','') = %s LIMIT 1",
                        (std_id_norm_key(variant),),
                    )
                    row = cur.fetchone()
                    if row:
                        files = self._fetch_files_mysql(cur, row["id"])
                        return _row_to_standard(row, files)
                    cur.execute(
                        f"SELECT * FROM std_base WHERE {std_compact} = %s LIMIT 1",
                        (std_id_compact_key(variant),),
                    )
                    row = cur.fetchone()
                    if row:
                        files = self._fetch_files_mysql(cur, row["id"])
                        return _row_to_standard(row, files)
            return None

        if not SQLITE_PATH.is_file():
            return None
        with self._sqlite() as conn:
            for variant in std_id_lookup_variants(q):
                cur = conn.execute(
                    "SELECT * FROM std_base WHERE std_id = ? OR std_id_norm = ? LIMIT 1",
                    (variant, std_id_norm_key(variant)),
                )
                row = cur.fetchone()
                if row:
                    d = dict(row)
                    files = self._fetch_files_sqlite(conn, d["id"])
                    return _row_to_standard(d, files)
            cur = conn.execute(
                "SELECT * FROM std_base WHERE std_id_norm = ? LIMIT 1",
                (norm,),
            )
            row = cur.fetchone()
            if row:
                d = dict(row)
                files = self._fetch_files_sqlite(conn, d["id"])
                return _row_to_standard(d, files)
            cur = conn.execute(
                "SELECT * FROM std_base WHERE std_id_norm = ? LIMIT 1",
                (compact,),
            )
            row = cur.fetchone()
            if row:
                d = dict(row)
                files = self._fetch_files_sqlite(conn, d["id"])
                return _row_to_standard(d, files)
            cur = conn.execute(
                "SELECT * FROM std_base WHERE UPPER(std_id) LIKE ? LIMIT 8",
                (f"%{q.strip().upper()}%",),
            )
            for row in cur.fetchall():
                d = dict(row)
                sid = d.get("std_id") or ""
                if std_id_norm_key(sid) == norm or std_id_compact_key(sid) == compact:
                    files = self._fetch_files_sqlite(conn, d["id"])
                    return _row_to_standard(d, files)
        return None

    def _has_pdf_sqlite(self, conn, base_id: int) -> bool:
        row = conn.execute(
            "SELECT 1 FROM std_filepath WHERE base_id = ? LIMIT 1", (base_id,)
        ).fetchone()
        return row is not None

    def _has_pdf_mysql(self, cur, base_id: int) -> bool:
        cur.execute(
            "SELECT 1 FROM std_filepath WHERE base_id = %s LIMIT 1", (base_id,)
        )
        return cur.fetchone() is not None

    def _folder_exists_sql(self, std_folder: str | None) -> tuple[str, tuple]:
        if not std_folder:
            return "", ()
        return (
            " AND EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id AND f.file_path LIKE ?)",
            (f"%{std_folder}%",),
        )

    def _row_to_lite(self, row: dict, has_pdf: bool) -> dict:
        ex = row.get("ex_state")
        return {
            "id": row["id"],
            "std_id": row.get("std_id") or "",
            "std_chinesename": row.get("std_chinesename"),
            "std_type": row.get("std_type"),
            "std_status": row.get("std_status"),
            "ex_state": ex,
            "ex_state_label": EX_STATE_LABEL.get(ex, row.get("std_status") or "未知"),
            "release_date": row.get("release_date"),
            "implement_date": row.get("implement_date"),
            "has_pdf": has_pdf,
        }

    def list_std_types(self, limit: int = 80) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        if self._mysql_available():
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT DISTINCT std_type FROM std_base
                    WHERE std_type IS NOT NULL AND std_type != ''
                    ORDER BY std_type LIMIT %s
                    """,
                    (limit,),
                )
                for row in cur.fetchall():
                    t = (row.get("std_type") or "").strip()
                    if t and t not in seen:
                        seen.add(t)
                        out.append(t)
        elif SQLITE_PATH.is_file():
            with self._sqlite() as conn:
                cur = conn.execute(
                    """
                    SELECT DISTINCT std_type FROM std_base
                    WHERE std_type IS NOT NULL AND std_type != ''
                    ORDER BY std_type LIMIT ?
                    """,
                    (limit,),
                )
                for row in cur.fetchall():
                    t = (dict(row).get("std_type") or "").strip()
                    if t and t not in seen:
                        seen.add(t)
                        out.append(t)
        return out

    def search_page(
        self,
        query: str,
        page: int = 1,
        per_page: int = 10,
        *,
        pdf_only: bool = True,
        std_folder: str | None = None,
    ) -> dict:
        q = (query or "").strip()
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        if not q:
            return self._empty_page(page, per_page, "text")
        if self._mysql_available():
            return self._search_page_mysql(
                q, page, per_page, offset, pdf_only, std_folder
            )
        return self._search_page_sqlite(q, page, per_page, offset, pdf_only, std_folder)

    def browse_page(
        self,
        page: int = 1,
        per_page: int = 10,
        *,
        pdf_only: bool = True,
        std_folder: str | None = None,
    ) -> dict:
        """首页默认列表：按发布年份、标准号倒序。"""
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        if self._mysql_available():
            return self._browse_page_mysql(
                page, per_page, offset, pdf_only, std_folder
            )
        return self._browse_page_sqlite(
            page, per_page, offset, pdf_only, std_folder
        )

    def _browse_page_sqlite(
        self,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
    ) -> dict:
        if not SQLITE_PATH.is_file():
            return self._empty_page(page, per_page, "browse")
        where_parts: list[str] = []
        args: list = []
        if pdf_only:
            where_parts.append(
                "EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            )
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        where = (" AND ".join(where_parts) if where_parts else "1=1") + folder_sql
        args.extend(folder_args)
        order = "ORDER BY substr(b.release_date, 1, 4) DESC, b.std_id DESC"
        with self._sqlite() as conn:
            cur = conn.execute(
                f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE {where}",
                args,
            )
            total = int(cur.fetchone()[0])
            cur = conn.execute(
                f"""
                SELECT DISTINCT b.* FROM std_base b
                WHERE {where}
                {order}
                LIMIT ? OFFSET ?
                """,
                (*args, per_page, offset),
            )
            rows = [dict(r) for r in cur.fetchall()]
            items = [
                self._row_to_lite(r, self._has_pdf_sqlite(conn, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "browse",
            "pdf_only": pdf_only,
            "browse": True,
        }

    def _browse_page_mysql(
        self,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
    ) -> dict:
        where_parts: list[str] = []
        args: list = []
        if pdf_only:
            where_parts.append(
                "EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            )
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        if folder_sql:
            folder_sql = folder_sql.replace("?", "%s")
        where = (" AND ".join(where_parts) if where_parts else "1=1") + folder_sql
        args.extend(folder_args)
        order = "ORDER BY substr(b.release_date, 1, 4) DESC, b.std_id DESC"
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE {where}",
                args,
            )
            total = int(cur.fetchone()["c"])
            cur.execute(
                f"""
                SELECT DISTINCT b.* FROM std_base b
                WHERE {where}
                {order}
                LIMIT %s OFFSET %s
                """,
                (*args, per_page, offset),
            )
            rows = list(cur.fetchall())
            items = [
                self._row_to_lite(r, self._has_pdf_mysql(cur, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "browse",
            "pdf_only": pdf_only,
            "browse": True,
        }

    def _empty_page(self, page: int, per_page: int, mode: str) -> dict:
        return {
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "items": [],
            "search_mode": mode,
        }

    def _search_page_sqlite(
        self,
        q: str,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
    ) -> dict:
        if not SQLITE_PATH.is_file():
            return self._empty_page(page, per_page, "text")
        clause, clause_args = build_keyword_match_clause(q, param="?", use_std_id_norm=True)
        order_sql, order_args = keyword_match_order_by(q, param="?")
        where_parts = [clause]
        args: list = list(clause_args)
        if pdf_only:
            where_parts.append(
                "EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            )
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        where = " AND ".join(where_parts) + folder_sql
        args.extend(folder_args)
        with self._sqlite() as conn:
            cur = conn.execute(
                f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE {where}",
                args,
            )
            total = int(cur.fetchone()[0])
            cur = conn.execute(
                f"""
                SELECT DISTINCT b.* FROM std_base b
                WHERE {where}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                (*args, *order_args, per_page, offset),
            )
            rows = [dict(r) for r in cur.fetchall()]
            items = [
                self._row_to_lite(r, self._has_pdf_sqlite(conn, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "text",
            "pdf_only": pdf_only,
        }

    def _search_page_mysql(
        self,
        q: str,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
    ) -> dict:
        clause, clause_args = build_keyword_match_clause(q, param="%s", use_std_id_norm=False)
        order_sql, order_args = mysql_keyword_match_order_by(q)
        where_parts = [clause]
        args: list = list(clause_args)
        if pdf_only:
            where_parts.append(
                "EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            )
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        if folder_sql:
            folder_sql = folder_sql.replace("?", "%s")
        where = " AND ".join(where_parts) + folder_sql
        args.extend(folder_args)
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE {where}",
                args,
            )
            total = int(cur.fetchone()["c"])
            cur.execute(
                f"""
                SELECT DISTINCT b.* FROM std_base b
                WHERE {where}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
                """,
                (*args, *order_args, per_page, offset),
            )
            rows = list(cur.fetchall())
            items = [
                self._row_to_lite(r, self._has_pdf_mysql(cur, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "text",
            "pdf_only": pdf_only,
        }

    def search_page_advanced(
        self,
        query: str,
        page: int = 1,
        per_page: int = 10,
        *,
        pdf_only: bool = True,
        std_folder: str | None = None,
        filters=None,
    ) -> dict:
        from core.search_filters import AdvancedFilters, build_advanced_where

        q = (query or "").strip()
        flt: AdvancedFilters = filters or AdvancedFilters()
        if not q and not flt.active():
            return self._empty_page(page, per_page, "advanced")
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        from core.unit_geo import geo_index_ready, needs_geo_filter

        if needs_geo_filter(flt) and geo_index_ready():
            return self._search_page_advanced_sqlite(
                q, page, per_page, offset, pdf_only, std_folder, flt
            )
        if self._mysql_available():
            return self._search_page_advanced_mysql(
                q, page, per_page, offset, pdf_only, std_folder, flt
            )
        return self._search_page_advanced_sqlite(
            q, page, per_page, offset, pdf_only, std_folder, flt
        )

    def _search_page_advanced_sqlite(
        self,
        q: str,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
        filters,
    ) -> dict:
        from core.search_filters import build_advanced_where

        if not SQLITE_PATH.is_file():
            return self._empty_page(page, per_page, "advanced")
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        where_extra, args = build_advanced_where(
            filters,
            q,
            pdf_only=pdf_only,
            std_folder=std_folder,
            folder_sql=folder_sql,
            folder_args=tuple(folder_args),
        )
        base_where = "1=1" + where_extra
        from core.unit_geo import attach_units_db

        with self._sqlite() as conn:
            attach_units_db(conn)
            cur = conn.execute(
                f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE {base_where}",
                args,
            )
            total = int(cur.fetchone()[0])
            cur = conn.execute(
                f"""
                SELECT DISTINCT b.* FROM std_base b
                WHERE {base_where}
                ORDER BY b.std_id
                LIMIT ? OFFSET ?
                """,
                (*args, per_page, offset),
            )
            rows = [dict(r) for r in cur.fetchall()]
            items = [
                self._row_to_lite(r, self._has_pdf_sqlite(conn, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "advanced",
            "pdf_only": pdf_only,
        }

    def _search_page_advanced_mysql(
        self,
        q: str,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
        filters,
    ) -> dict:
        from core.search_filters import build_advanced_where

        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        where_extra, args = build_advanced_where(
            filters,
            q,
            pdf_only=pdf_only,
            std_folder=std_folder,
            folder_sql=folder_sql.replace("?", "%s") if folder_sql else "",
            folder_args=tuple(folder_args),
            param="%s",
        )
        base_where = "1=1" + where_extra
        mysql_args = list(args)
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE {base_where}",
                mysql_args,
            )
            total = int(cur.fetchone()["c"])
            cur.execute(
                f"""
                SELECT DISTINCT b.* FROM std_base b
                WHERE {base_where}
                ORDER BY b.std_id
                LIMIT %s OFFSET %s
                """,
                (*mysql_args, per_page, offset),
            )
            rows = list(cur.fetchall())
            items = [
                self._row_to_lite(r, self._has_pdf_mysql(cur, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "advanced",
            "pdf_only": pdf_only,
        }

    def search_page_cluster(
        self,
        keywords: list[str],
        page: int = 1,
        per_page: int = 10,
        *,
        pdf_only: bool = True,
        std_folder: str | None = None,
        primary_keyword: str | None = None,
    ) -> dict:
        kws: list[str] = []
        seen: set[str] = set()
        for k in keywords:
            t = (k or "").strip()
            if t and t not in seen:
                seen.add(t)
                kws.append(t)
        if not kws:
            return self._empty_page(page, per_page, "product_cluster")
        kws = kws[:24]
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        primary = (primary_keyword or kws[0]).strip()
        if SQLITE_PATH.is_file():
            return self._search_page_cluster_sqlite(
                kws, primary, page, per_page, offset, pdf_only, std_folder
            )
        if self._mysql_available():
            return self._search_page_cluster_mysql(
                kws, primary, page, per_page, offset, pdf_only, std_folder
            )
        return self._search_page_cluster_sqlite(
            kws, primary, page, per_page, offset, pdf_only, std_folder
        )

    def _cluster_score_sql(
        self, keywords: list[str], primary: str, mysql: bool
    ) -> tuple[str, list]:
        ph = "%s" if mysql else "?"
        parts: list[str] = []
        args: list = []
        for kw in keywords:
            pat = f"%{kw}%"
            weight = 2 if kw == primary else 1
            parts.append(
                f"(CASE WHEN b.std_chinesename LIKE {ph} THEN {weight} ELSE 0 END)"
            )
            args.append(pat)
        return " + ".join(parts) or "0", args

    def _cluster_name_where_sql(
        self, keywords: list[str], mysql: bool
    ) -> tuple[str, list]:
        ph = "%s" if mysql else "?"
        parts = [f"b.std_chinesename LIKE {ph}" for _ in keywords]
        args = [f"%{kw}%" for kw in keywords]
        return "(" + " OR ".join(parts) + ")", args

    def _search_page_cluster_sqlite(
        self,
        keywords: list[str],
        primary: str,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
    ) -> dict:
        if not SQLITE_PATH.is_file():
            return self._empty_page(page, per_page, "product_cluster")
        score_sql, score_args = self._cluster_score_sql(keywords, primary, False)
        where_sql, where_args = self._cluster_name_where_sql(keywords, False)
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        pdf_sql = (
            " AND EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            if pdf_only
            else ""
        )
        with self._sqlite() as conn:
            count_sql = f"""
                SELECT COUNT(DISTINCT b.id) AS c FROM std_base b
                WHERE {where_sql}{pdf_sql}{folder_sql}
            """
            search_sql = f"""
                SELECT DISTINCT b.*, ({score_sql}) AS match_score
                FROM std_base b
                WHERE {where_sql}{pdf_sql}{folder_sql}
                ORDER BY match_score DESC, b.std_id
                LIMIT ? OFFSET ?
            """
            count_args = where_args + list(folder_args)
            cur = conn.execute(count_sql, count_args)
            total = int(cur.fetchone()[0])
            cur = conn.execute(
                search_sql,
                where_args + score_args + list(folder_args) + [per_page, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]
            items = [
                self._row_to_lite(r, self._has_pdf_sqlite(conn, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "product_cluster",
            "pdf_only": pdf_only,
        }

    def _search_page_cluster_mysql(
        self,
        keywords: list[str],
        primary: str,
        page: int,
        per_page: int,
        offset: int,
        pdf_only: bool,
        std_folder: str | None,
    ) -> dict:
        score_sql, score_args = self._cluster_score_sql(keywords, primary, True)
        where_sql, where_args = self._cluster_name_where_sql(keywords, True)
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        if folder_sql:
            folder_sql = folder_sql.replace("?", "%s")
        pdf_sql = (
            " AND EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            if pdf_only
            else ""
        )
        with self._mysql() as conn:
            cur = conn.cursor()
            count_sql = f"""
                SELECT COUNT(DISTINCT b.id) AS c FROM std_base b
                WHERE {where_sql}{pdf_sql}{folder_sql}
            """
            search_sql = f"""
                SELECT DISTINCT b.*, ({score_sql}) AS match_score
                FROM std_base b
                WHERE {where_sql}{pdf_sql}{folder_sql}
                ORDER BY match_score DESC, b.std_id
                LIMIT %s OFFSET %s
            """
            cur.execute(count_sql, where_args + list(folder_args))
            total = int(cur.fetchone()["c"])
            cur.execute(
                search_sql,
                where_args + score_args + list(folder_args) + [per_page, offset],
            )
            rows = list(cur.fetchall())
            items = [
                self._row_to_lite(r, self._has_pdf_mysql(cur, r["id"])) for r in rows
            ]
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
            "search_mode": "product_cluster",
            "pdf_only": pdf_only,
        }


db = Database()
