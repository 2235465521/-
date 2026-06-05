"""标准按全部起草单位地址归类（省/市/区县/单位名）。"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from paths import UNITS_DB_PATH

if TYPE_CHECKING:
    from core.search_filters import AdvancedFilters

_INDEXES_READY = False


def geo_index_ready() -> bool:
    if not UNITS_DB_PATH.is_file():
        return False
    try:
        conn = sqlite3.connect(UNITS_DB_PATH)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM std_unit_geo"
            ).fetchone()
            return bool(row and row[0] > 0)
        except sqlite3.Error:
            return False
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def needs_geo_filter(filters: AdvancedFilters) -> bool:
    return bool(
        filters.province
        or filters.city
        or filters.county
        or (
            filters.company
            and filters.unit_rank is None
            and not filters.unit_rank_gt3
        )
    )


def ensure_search_indexes(conn: sqlite3.Connection) -> None:
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_geo_unit_name ON std_unit_geo(unit_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rel_base_rank "
            "ON std_unit_relation(base_id, rank_order)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rel_rank_unit "
            "ON std_unit_relation(rank_order, unit_id)"
        )
        conn.commit()
        _INDEXES_READY = True
    except sqlite3.Error:
        pass


def attach_units_db(conn: sqlite3.Connection) -> bool:
    if not geo_index_ready():
        return False
    conn.execute("ATTACH DATABASE ? AS udb", (str(UNITS_DB_PATH),))
    ensure_search_indexes(conn)
    return True


def build_geo_where(
    filters: AdvancedFilters,
    *,
    param: str = "?",
    mysql: bool = False,
) -> tuple[str, list]:
    """任一起草单位地址匹配即归入该地区。"""
    if not needs_geo_filter(filters):
        return "", []

    if mysql:
        return _build_geo_where_mysql(filters, param=param)
    return _build_geo_where_sqlite(filters, param=param)


def _build_geo_where_mysql(
    filters: AdvancedFilters, *, param: str = "%s"
) -> tuple[str, list]:
    inner: list[str] = []
    args: list = []

    if filters.province:
        inner.append(f"a.province_name = {param}")
        args.append(filters.province)
    if filters.city:
        inner.append(f"a.city_name = {param}")
        args.append(filters.city)
    if filters.county:
        inner.append(f"a.county_name = {param}")
        args.append(filters.county)
    if filters.company and filters.unit_rank is None and not filters.unit_rank_gt3:
        inner.append(f"u.unit_name LIKE {param}")
        args.append(f"%{filters.company}%")

    if not inner:
        return "", []

    extra = " AND " + " AND ".join(inner)
    area_join = """
              SELECT ad.area_code FROM area_dict ad
              WHERE u.area_code IS NOT NULL AND u.area_code != ''
                AND (ad.area_code = u.area_code OR ad.area_code LIKE CONCAT(u.area_code, '%%'))
              ORDER BY LENGTH(ad.area_code) DESC
              LIMIT 1
    """
    sql = f"""
        EXISTS (
          SELECT 1 FROM std_unit_relation r
          INNER JOIN unit_dict u ON u.unit_id = r.unit_id
          LEFT JOIN area_dict a ON a.area_code = ({area_join})
          WHERE r.base_id = b.id
            {extra}
        )
    """
    return sql, args


def _build_geo_where_sqlite(
    filters: AdvancedFilters, *, param: str = "?"
) -> tuple[str, list]:
    if not geo_index_ready():
        return "", []

    inner: list[str] = []
    args: list = []

    if filters.province:
        inner.append(f"g.province_name = {param}")
        args.append(filters.province)
    if filters.city:
        inner.append(f"g.city_name = {param}")
        args.append(filters.city)
    if filters.county:
        inner.append(f"g.county_name = {param}")
        args.append(filters.county)
    if filters.company and filters.unit_rank is None and not filters.unit_rank_gt3:
        inner.append(f"g.unit_name LIKE {param}")
        args.append(f"%{filters.company}%")

    if not inner:
        return "", []

    extra = " AND " + " AND ".join(inner)
    sql = f"""
        EXISTS (
          SELECT 1 FROM udb.std_unit_geo g
          WHERE g.base_id = b.id
            {extra}
        )
    """
    return sql, args


def build_rank_where(
    filters: AdvancedFilters,
    *,
    param: str = "?",
    mysql: bool = False,
) -> tuple[str, list]:
    """按起草单位在标准中的排序位次筛选（需配合单位名）。"""
    if not filters.company:
        return "", []
    if filters.unit_rank is None and not filters.unit_rank_gt3:
        return "", []

    if filters.unit_rank_gt3:
        rank_sql = f"r.rank_order > {param}"
        rank_args: list = [3, f"%{filters.company}%"]
    else:
        rank_sql = f"r.rank_order = {param}"
        rank_args = [filters.unit_rank, f"%{filters.company}%"]

    if mysql:
        sql = f"""
        EXISTS (
          SELECT 1 FROM std_unit_relation r
          INNER JOIN unit_dict u ON u.unit_id = r.unit_id
          WHERE r.base_id = b.id
            AND {rank_sql}
            AND u.unit_name LIKE {param}
        )
        """
    else:
        if not geo_index_ready():
            return "", []
        sql = f"""
        EXISTS (
          SELECT 1 FROM udb.std_unit_relation r
          INNER JOIN udb.unit_dict u ON u.unit_id = r.unit_id
          WHERE r.base_id = b.id
            AND {rank_sql}
            AND u.unit_name LIKE {param}
        )
        """
    return sql, rank_args
