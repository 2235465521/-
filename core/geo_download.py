"""按省/市/县（全部起草单位地址）批量列出标准并打包下载 — 仅 MySQL。"""
from __future__ import annotations

from typing import Any

from core.db import db
from core.search_filters import AdvancedFilters, build_advanced_where

MAX_GEO_DOWNLOAD = 5000


def _region_label(filters: AdvancedFilters) -> str:
    parts = [filters.province, filters.city, filters.county]
    return "_".join(p for p in parts if p) or "地区"


def geo_download_ready() -> bool:
    return db._mysql_available()


def geo_download_status() -> dict[str, Any]:
    return {
        "ready": geo_download_ready(),
        "mysql": db._mysql_available(),
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
            "error": "地区批量下载未就绪，请配置 MySQL 标准库",
        }

    total = _count_geo_mysql(filters, q=q, pdf_only=pdf_only)
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
    return _list_geo_mysql(filters, q=q, pdf_only=pdf_only, limit=limit)


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
    folder_sql, folder_args = db._folder_exists_sql(None)
    where_extra, args = build_advanced_where(
        filters,
        q,
        pdf_only=pdf_only,
        std_folder=None,
        folder_sql=folder_sql,
        folder_args=tuple(folder_args),
        param="%s",
    )
    return where_extra, list(args)
