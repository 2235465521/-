from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import pymysql

from config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from core.std_normalize import (
    db_filepath_matches_std,
    normalize_std_id,
    sql_std_id_norm_expr,
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

    def backend_name(self) -> str:
        return "MySQL" if self._mysql_available() else "未就绪"

    def is_ready(self) -> bool:
        return self._mysql_available()

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

    def search(self, query: str, limit: int = 20) -> list[StandardInfo]:
        q = query.strip()
        if not q or not self._mysql_available():
            return []
        norm = normalize_std_id(q)
        sid_norm = sql_std_id_norm_expr("std_id")
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
                    f"SELECT * FROM std_base WHERE {sid_norm} = %s LIMIT %s",
                    (norm, limit),
                ),
                (
                    f"SELECT * FROM std_base WHERE {sid_norm} LIKE %s LIMIT %s",
                    (f"{norm}%", limit),
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

    def get_by_id(self, base_id: int) -> StandardInfo | None:
        if not self._mysql_available():
            return None
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM std_base WHERE id = %s", (base_id,))
            row = cur.fetchone()
            if not row:
                return None
            files = self._fetch_files_mysql(cur, base_id)
            return _row_to_standard(row, files)

    def get_filepath_record(self, file_id: int) -> dict | None:
        if not self._mysql_available():
            return None
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, base_id, file_path, file_name FROM std_filepath WHERE id = %s",
                (file_id,),
            )
            return cur.fetchone()

    def search_std_id(self, query: str) -> StandardInfo | None:
        """仅按标准号精确/变体匹配（批量下载用，不用名称模糊）。

        兼容无空格紧凑写法：GB12523 / GBT12523 / GB/T12523 等。
        """
        q = (query or "").strip()
        if not q or not self._mysql_available():
            return None
        norm = normalize_std_id(q)
        sid_norm = sql_std_id_norm_expr("std_id")
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT * FROM std_base
                WHERE {sid_norm} = %s OR std_id = %s
                LIMIT 1
                """,
                (norm, q),
            )
            row = cur.fetchone()
            if row:
                files = self._fetch_files_mysql(cur, row["id"])
                return _row_to_standard(row, files)

            # 无空格 / 无年号前缀：GB12523 → GB 12523-2025
            cur.execute(
                f"SELECT * FROM std_base WHERE {sid_norm} LIKE %s LIMIT 8",
                (f"{norm}%",),
            )
            candidates = list(cur.fetchall())
            exactish = [
                r
                for r in candidates
                if normalize_std_id(r.get("std_id") or "") == norm
            ]
            if exactish:
                files = self._fetch_files_mysql(cur, exactish[0]["id"])
                return _row_to_standard(exactish[0], files)
            if "-" not in norm:
                year_hits = [
                    r
                    for r in candidates
                    if normalize_std_id(r.get("std_id") or "").startswith(norm + "-")
                ]
                if year_hits:
                    files = self._fetch_files_mysql(cur, year_hits[0]["id"])
                    return _row_to_standard(year_hits[0], files)
            if len(candidates) == 1:
                files = self._fetch_files_mysql(cur, candidates[0]["id"])
                return _row_to_standard(candidates[0], files)
        return None

    def _has_pdf_mysql(self, cur, base_id: int) -> bool:
        files = self._fetch_files_mysql(cur, base_id)
        cur.execute("SELECT std_id FROM std_base WHERE id = %s", (base_id,))
        row = cur.fetchone()
        std_id = (row.get("std_id") if row else "") or ""
        return self._files_match_std(std_id, files)

    @staticmethod
    def _files_match_std(std_id: str, files: list[dict]) -> bool:
        for f in files or []:
            if db_filepath_matches_std(std_id, f.get("file_name"), f.get("file_path")):
                return True
        return False

    def _fetch_files_by_ids_mysql(self, cur, base_ids: list[int]) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {i: [] for i in base_ids}
        if not base_ids:
            return out
        placeholders = ",".join(["%s"] * len(base_ids))
        cur.execute(
            f"""
            SELECT id, base_id, file_path, file_name, file_size
            FROM std_filepath
            WHERE base_id IN ({placeholders})
            ORDER BY file_name
            """,
            tuple(base_ids),
        )
        for row in cur.fetchall():
            bid = int(row["base_id"])
            out.setdefault(bid, []).append(row)
        return out

    def _rows_to_lite_with_pdf(
        self, rows: list[dict], files_by_id: dict[int, list[dict]]
    ) -> list[dict]:
        items = []
        for r in rows:
            bid = int(r["id"])
            std_id = r.get("std_id") or ""
            has_pdf = self._files_match_std(std_id, files_by_id.get(bid) or [])
            items.append(self._row_to_lite(r, has_pdf))
        return items

    def _folder_exists_sql(self, std_folder: str | None) -> tuple[str, tuple]:
        if not std_folder:
            return "", ()
        return (
            " AND EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id AND f.file_path LIKE %s)",
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
            "match_status": "ok" if has_pdf else "no_pdf",
        }

    def list_std_types(self, limit: int = 500) -> list[str]:
        if not self._mysql_available():
            return []
        seen: set[str] = set()
        out: list[str] = []
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT std_type FROM std_base
                WHERE std_type IS NOT NULL AND TRIM(std_type) != ''
                ORDER BY std_type
                LIMIT %s
                """,
                (max(1, min(int(limit), 2000)),),
            )
            for row in cur.fetchall():
                t = (row.get("std_type") or "").strip()
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
        if not self._mysql_available():
            return self._empty_page(page, per_page, "text")
        return self._search_page_mysql(
            q, page, per_page, offset, pdf_only, std_folder
        )

    def _empty_page(self, page: int, per_page: int, mode: str) -> dict:
        return {
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "items": [],
            "search_mode": mode,
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
        from core.search_filters import _looks_like_file_keyword

        pattern = f"%{q}%"
        norm = normalize_std_id(q)
        sid_norm = sql_std_id_norm_expr("b.std_id")
        if _looks_like_file_keyword(q):
            # 官方写法「代号 空格 顺序号」；兼容无空格 GB12523 / GBT12523 / GB/T12523
            where_parts = [
                f"(b.std_id LIKE %s OR {sid_norm} = %s OR {sid_norm} LIKE %s "
                f"OR b.std_chinesename LIKE %s)"
            ]
            args: list = [f"{q}%", norm, f"{norm}%", pattern]
        else:
            where_parts = ["b.std_chinesename LIKE %s"]
            args = [pattern]
        if pdf_only:
            where_parts.append(
                "EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
            )
        folder_sql, folder_args = self._folder_exists_sql(std_folder)
        where = " AND ".join(where_parts) + folder_sql
        args.extend(folder_args)
        with self._mysql() as conn:
            cur = conn.cursor()
            total = self._mysql_count_capped(cur, where, args)
            cur.execute(
                f"""
                SELECT b.* FROM std_base b
                WHERE {where}
                ORDER BY b.std_id
                LIMIT %s OFFSET %s
                """,
                (*args, per_page, offset),
            )
            rows = list(cur.fetchall())
            files_by_id = self._fetch_files_by_ids_mysql(
                cur, [int(r["id"]) for r in rows]
            )
            items = self._rows_to_lite_with_pdf(rows, files_by_id)
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

    _MYSQL_COUNT_CAP = 10001

    def _mysql_count_capped(self, cur, where: str, args: list) -> int:
        cur.execute(
            f"""
            SELECT COUNT(*) AS c FROM (
              SELECT b.id FROM std_base b
              WHERE {where}
              LIMIT %s
            ) t
            """,
            (*args, self._MYSQL_COUNT_CAP),
        )
        return int(cur.fetchone()["c"])

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
        from core.search_filters import AdvancedFilters

        q = (query or "").strip()
        flt: AdvancedFilters = filters or AdvancedFilters()
        if not q and not flt.active():
            return self._empty_page(page, per_page, "advanced")
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        if not self._mysql_available():
            return self._empty_page(page, per_page, "advanced")
        return self._search_page_advanced_mysql(
            q, page, per_page, offset, pdf_only, std_folder, flt
        )

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
            folder_sql=folder_sql,
            folder_args=tuple(folder_args),
            param="%s",
        )
        base_where = "1=1" + where_extra
        mysql_args = list(args)
        with self._mysql() as conn:
            cur = conn.cursor()
            total = self._mysql_count_capped(cur, base_where, mysql_args)
            cur.execute(
                f"""
                SELECT b.* FROM std_base b
                WHERE {base_where}
                ORDER BY b.std_id
                LIMIT %s OFFSET %s
                """,
                (*mysql_args, per_page, offset),
            )
            rows = list(cur.fetchall())
            files_by_id = self._fetch_files_by_ids_mysql(
                cur, [int(r["id"]) for r in rows]
            )
            items = self._rows_to_lite_with_pdf(rows, files_by_id)
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


db = Database()
