"""读取 MySQL 预统计汇总表（stats_* / dim_region）。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from food_inspection.db import connection
from food_inspection.mysql_search import mysql_enabled

_YEAR_RE = re.compile(r"^[0-9]{4}$")


def stats_tables_ready() -> bool:
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM stats_global LIMIT 1")
            return bool(cur.fetchone())
    except Exception:
        return False



def _year_filter_sql(
    date_from: str | None,
    date_to: str | None,
    *,
    prefix: str = "",
) -> tuple[str, dict[str, Any]]:
    col = f"{prefix}year" if prefix else "year"
    if not date_from and not date_to:
        return "", {}
    start_year = date.fromisoformat(date_from).year if date_from else 2000
    end_year = date.fromisoformat(date_to).year if date_to else 2099
    clause = (
        f"({col} REGEXP '^[0-9]{{4}}$' "
        f"AND CAST({col} AS UNSIGNED) BETWEEN %(year_from)s AND %(year_to)s)"
    )
    return clause, {"year_from": start_year, "year_to": end_year}


def read_global_stats() -> dict[str, Any] | None:
    if not stats_tables_ready():
        return None
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  qualified_count,
                  unqualified_row_count,
                  unqualified_item_count,
                  total_files,
                  refreshed_at
                FROM stats_global
                WHERE id = 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None

            cur.execute(
                """
                SELECT province,
                       SUM(qualified_count + unqualified_row_count) AS cnt
                FROM stats_region
                GROUP BY province
                ORDER BY cnt DESC
                """
            )
            provinces = {r["province"]: int(r["cnt"] or 0) for r in cur.fetchall()}

        return {
            "qualified_count": int(row["qualified_count"] or 0),
            "unqualified_count": int(row["unqualified_item_count"] or 0),
            "unqualified_row_count": int(row["unqualified_row_count"] or 0),
            "total_files": int(row["total_files"] or 0),
            "parsed_files": int(row["total_files"] or 0),
            "provinces": provinces,
            "count_mode": "item",
            "data_source": "mysql_stats_tables",
            "stats_refreshed_at": str(row["refreshed_at"] or ""),
        }
    except Exception:
        return None


def read_provinces() -> list[str] | None:
    if not stats_tables_ready():
        return None
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT province FROM dim_region "
                "ORDER BY province"
            )
            return [r["province"] for r in cur.fetchall()]
    except Exception:
        return None


def read_cities(province: str = "全部") -> list[str] | None:
    if not stats_tables_ready():
        return None
    try:
        with connection() as conn, conn.cursor() as cur:
            if province and province != "全部":
                cur.execute(
                    "SELECT city FROM dim_region "
                    "WHERE province = %s AND city <> '' ORDER BY city",
                    (province,),
                )
            else:
                cur.execute(
                    "SELECT DISTINCT city FROM dim_region "
                    "WHERE city <> '' ORDER BY city"
                )
            return [r["city"] for r in cur.fetchall()]
    except Exception:
        return None


def read_overview_chart(
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any] | None:
    """从 stats_region / stats_global 读取总览图表（毫秒级，分类明细后续可扩展）。"""
    if not stats_tables_ready():
        return None

    from food_inspection.mysql_stats import _scope_label

    province = province or "全部"
    city = city or "全部"
    scope, scope_type = _scope_label(province, city)
    year_clause, year_params = _year_filter_sql(date_from, date_to)
    where_parts: list[str] = []
    params: dict[str, Any] = dict(year_params)

    if province != "全部":
        where_parts.append("province = %(province)s")
        params["province"] = province
    if city != "全部":
        where_parts.append("city = %(city)s")
        params["city"] = city
    if year_clause:
        where_parts.append(year_clause)

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  COALESCE(SUM(qualified_count), 0) AS q_count,
                  COALESCE(SUM(unqualified_row_count), 0) AS u_row_count
                FROM stats_region
                {where_sql}
                """,
                params,
            )
            row = cur.fetchone() or {}
            q_count = int(row.get("q_count") or 0)
            u_row_count = int(row.get("u_row_count") or 0)

            if province == "全部" and city == "全部" and not date_from and not date_to:
                cur.execute(
                    "SELECT unqualified_item_count FROM stats_global WHERE id = 1"
                )
                global_row = cur.fetchone() or {}
                u_count = int(global_row.get("unqualified_item_count") or u_row_count)
            else:
                u_count = u_row_count

        total = q_count + u_count
        return {
            "scope": scope,
            "scope_type": scope_type,
            "province": province,
            "city": city,
            "qualified_count": q_count,
            "unqualified_count": u_count,
            "total_count": total,
            "failure_rate": round(u_count / total * 100, 2) if total else 0,
            "categories": [],
            "unqualified_categories": [],
            "unqualified_categories_total": u_count,
            "unqualified_categorized_count": 0,
            "unqualified_uncategorized_count": u_count,
            "data_source": "mysql_stats_tables",
            "date_from": date_from or "",
            "date_to": date_to or "",
        }
    except Exception:
        return None


def read_overview_map(
    province: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
    city: str = "",
) -> dict[str, Any] | None:
    """从 stats_region 读取地图着色数据（区县级仍走实时查询）。"""
    if not stats_tables_ready():
        return None
    if city and city != "全部" and province != "全部":
        return None

    province = province or "全部"
    year_clause, year_params = _year_filter_sql(date_from, date_to)
    where_parts: list[str] = []
    params: dict[str, Any] = dict(year_params)

    if year_clause:
        where_parts.append(year_clause)

    try:
        with connection() as conn, conn.cursor() as cur:
            if province == "全部":
                where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
                cur.execute(
                    f"""
                    SELECT province AS name,
                           SUM(qualified_count) AS q_count,
                           SUM(unqualified_row_count) AS u_count
                    FROM stats_region
                    {where_sql}
                    GROUP BY province
                    HAVING name IS NOT NULL AND name <> ''
                    """,
                    params,
                )
                level = "province"
                scope = "全国"
            else:
                where_parts.append("province = %(province)s")
                params["province"] = province
                where_sql = " WHERE " + " AND ".join(where_parts)
                cur.execute(
                    f"""
                    SELECT city AS name,
                           SUM(qualified_count) AS q_count,
                           SUM(unqualified_row_count) AS u_count
                    FROM stats_region
                    {where_sql}
                    AND city IS NOT NULL AND city <> ''
                    GROUP BY city
                    """,
                    params,
                )
                level = "city"
                scope = province

            rows = cur.fetchall()

        from food_inspection.mysql_stats import _map_region_entry

        regions = [
            {
                "name": row["name"],
                **_map_region_entry(int(row["q_count"] or 0), int(row["u_count"] or 0)),
            }
            for row in rows
        ]
        regions.sort(key=lambda item: item["failure_rate"], reverse=True)
        rates = [item["failure_rate"] for item in regions if item["total_count"] > 0]
        return {
            "level": level,
            "scope": scope,
            "province": province if province != "全部" else "",
            "city": city if city and city != "全部" else "",
            "regions": regions,
            "max_failure_rate": max(rates) if rates else 0,
            "min_failure_rate": min(rates) if rates else 0,
            "data_source": "mysql_stats_tables",
            "date_from": date_from or "",
            "date_to": date_to or "",
        }
    except Exception:
        return None
