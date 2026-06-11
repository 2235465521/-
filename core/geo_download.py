"""按省/市/县（全部起草单位地址）批量列出标准并打包下载。"""
from __future__ import annotations

import sqlite3
from typing import Any

from core.db import db
from core.search_filters import AdvancedFilters, build_advanced_where
from core.unit_geo import attach_units_db, geo_index_ready
from paths import SQLITE_PATH, UNITS_DB_PATH

MAX_GEO_DOWNLOAD = 5000


def _region_label(filters: AdvancedFilters) -> str:
    parts = [filters.province, filters.city, filters.county]
    return "_".join(p for p in parts if p) or "地区"


def _geo_join_clauses(filters: AdvancedFilters, param: str = "?") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if filters.province:
        clauses.append(f"g.province_name = {param}")
        args.append(filters.province)
    if filters.city:
        clauses.append(f"g.city_name = {param}")
        args.append(filters.city)
    if filters.county:
        clauses.append(f"g.county_name = {param}")
        args.append(filters.county)
    if filters.company and filters.unit_rank is None and not filters.unit_rank_gt3:
        clauses.append(f"g.unit_name LIKE {param}")
        args.append(f"%{filters.company}%")
    if not clauses:
        return "", []
    return " AND ".join(clauses), args


def _other_filters(filters: AdvancedFilters) -> AdvancedFilters:
    return AdvancedFilters(
        ex_states=list(filters.ex_states),
        std_type=filters.std_type,
        product=filters.product,
        company=filters.company if (filters.unit_rank is not None or filters.unit_rank_gt3) else "",
        unit_rank=filters.unit_rank,
        unit_rank_gt3=filters.unit_rank_gt3,
        year_from=filters.year_from,
        year_to=filters.year_to,
    )


def geo_download_ready() -> bool:
    return geo_index_ready() or db._mysql_available()


def geo_download_status() -> dict[str, Any]:
    return {
        "ready": geo_download_ready(),
        "units_index": geo_index_ready(),
        "mysql": db._mysql_available(),
        "units_db": str(UNITS_DB_PATH),
        "max_download": MAX_GEO_DOWNLOAD,
    }


def count_geo_matches(
    filters: AdvancedFilters,
    *,
    q: str = "",
    pdf_only: bool = True,
) -> dict[str, Any]:
    if not filters.province:
        return {"ok": False, "error": "请选择省份"}
    if not geo_download_ready():
        return {
            "ok": False,
            "error": "地区批量下载未就绪，请配置 MySQL mydate 或运行 scripts/build_unit_index.py",
        }

    total = _count_geo_sqlite(filters, q=q, pdf_only=pdf_only)
    capped = min(total, MAX_GEO_DOWNLOAD)
    return {
        "ok": True,
        "total": total,
        "download_count": capped,
        "capped": total > MAX_GEO_DOWNLOAD,
        "limit": MAX_GEO_DOWNLOAD,
        "region": _region_label(filters),
        "pdf_only": pdf_only,
        "backend": db.backend_name(),
    }


def list_geo_base_ids(
    filters: AdvancedFilters,
    *,
    q: str = "",
    pdf_only: bool = True,
    limit: int = MAX_GEO_DOWNLOAD,
) -> list[int]:
    if not filters.province:
        return []
    limit = max(1, min(int(limit or MAX_GEO_DOWNLOAD), MAX_GEO_DOWNLOAD))
    return _list_geo_sqlite(filters, q=q, pdf_only=pdf_only, limit=limit)


def _count_geo_sqlite(
    filters: AdvancedFilters, *, q: str, pdf_only: bool
) -> int:
    if not geo_index_ready() or not SQLITE_PATH.is_file():
        return _count_geo_mysql(filters, q=q, pdf_only=pdf_only)
    geo_sql, geo_args = _geo_join_clauses(filters)
    other = _other_filters(filters)
    folder_sql, folder_args = db._folder_exists_sql(None)
    where_extra, other_args = build_advanced_where(
        other,
        q,
        pdf_only=pdf_only,
        std_folder=None,
        folder_sql=folder_sql,
        folder_args=tuple(folder_args),
    )
    sql = f"""
        SELECT COUNT(DISTINCT b.id) AS c
        FROM std_base b
        INNER JOIN udb.std_unit_geo g ON g.base_id = b.id
        WHERE {geo_sql}{where_extra}
    """
    with db._sqlite() as conn:
        if not attach_units_db(conn):
            return _count_geo_mysql(filters, q=q, pdf_only=pdf_only)
        row = conn.execute(sql, (*geo_args, *other_args)).fetchone()
        return int(row[0]) if row else 0


def _list_geo_sqlite(
    filters: AdvancedFilters, *, q: str, pdf_only: bool, limit: int
) -> list[int]:
    if not geo_index_ready() or not SQLITE_PATH.is_file():
        return _list_geo_mysql(filters, q=q, pdf_only=pdf_only, limit=limit)
    geo_sql, geo_args = _geo_join_clauses(filters)
    other = _other_filters(filters)
    folder_sql, folder_args = db._folder_exists_sql(None)
    where_extra, other_args = build_advanced_where(
        other,
        q,
        pdf_only=pdf_only,
        std_folder=None,
        folder_sql=folder_sql,
        folder_args=tuple(folder_args),
    )
    sql = f"""
        SELECT DISTINCT b.id
        FROM std_base b
        INNER JOIN udb.std_unit_geo g ON g.base_id = b.id
        WHERE {geo_sql}{where_extra}
        ORDER BY b.std_id
        LIMIT ?
    """
    with db._sqlite() as conn:
        if not attach_units_db(conn):
            return _list_geo_mysql(filters, q=q, pdf_only=pdf_only, limit=limit)
        rows = conn.execute(sql, (*geo_args, *other_args, limit)).fetchall()
        return [int(r[0]) for r in rows]


def _count_geo_mysql(
    filters: AdvancedFilters, *, q: str, pdf_only: bool
) -> int:
    if not db._mysql_available():
        return 0
    where_extra, args = _mysql_geo_where(filters, q=q, pdf_only=pdf_only)
    sql = f"SELECT COUNT(DISTINCT b.id) AS c FROM std_base b WHERE 1=1{where_extra}"
    with db._mysql() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def _list_geo_mysql(
    filters: AdvancedFilters, *, q: str, pdf_only: bool, limit: int
) -> list[int]:
    if not db._mysql_available():
        return []
    where_extra, args = _mysql_geo_where(filters, q=q, pdf_only=pdf_only)
    sql = f"""
        SELECT DISTINCT b.id
        FROM std_base b
        WHERE 1=1{where_extra}
        ORDER BY b.std_id
        LIMIT %s
    """
    with db._mysql() as conn:
        cur = conn.cursor()
        cur.execute(sql, (*args, limit))
        return [int(r["id"]) for r in cur.fetchall()]


def _mysql_geo_where(
    filters: AdvancedFilters, *, q: str, pdf_only: bool
) -> tuple[str, list[Any]]:
    other = _other_filters(filters)
    folder_sql, folder_args = db._folder_exists_sql(None)
    where_extra, args = build_advanced_where(
        filters,
        q,
        pdf_only=pdf_only,
        std_folder=None,
        folder_sql=folder_sql.replace("?", "%s") if folder_sql else "",
        folder_args=tuple(folder_args),
        param="%s",
    )
    return where_extra, list(args)
