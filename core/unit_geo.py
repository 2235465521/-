"""标准按全部起草单位地址归类（省/市/区县/单位名）— 仅 MySQL。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.search_filters import AdvancedFilters


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


def build_geo_where(
    filters: AdvancedFilters,
    *,
    param: str = "%s",
    mysql: bool = True,
) -> tuple[str, list]:
    """任一起草单位地址匹配即归入该地区。"""
    del mysql  # 兼容旧调用签名，始终生成 MySQL SQL
    if not needs_geo_filter(filters):
        return "", []

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
    sql = f"""
        EXISTS (
          SELECT 1 FROM std_unit_relation r
          INNER JOIN unit_dict u ON u.unit_id = r.unit_id
          INNER JOIN area_dict a ON a.area_code = u.area_code
          WHERE r.base_id = b.id
            {extra}
        )
    """
    return sql, args


def build_rank_where(
    filters: AdvancedFilters,
    *,
    param: str = "%s",
    mysql: bool = True,
) -> tuple[str, list]:
    """按起草单位在标准中的排序位次筛选（需配合单位名）。"""
    del mysql  # 兼容旧调用签名，始终生成 MySQL SQL
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

    sql = f"""
        EXISTS (
          SELECT 1 FROM std_unit_relation r
          INNER JOIN unit_dict u ON u.unit_id = r.unit_id
          WHERE r.base_id = b.id
            AND {rank_sql}
            AND u.unit_name LIKE {param}
        )
    """
    return sql, rank_args
