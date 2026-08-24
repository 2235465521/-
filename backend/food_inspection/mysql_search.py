"""MySQL 分类检索：公司、省市县、产品、不合格项/原因、食品分类。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from config import MYSQL_TABLE, MYSQL_URL
from food_inspection.db import row_to_record

_ENGINE = None


def mysql_enabled() -> bool:
    return bool(MYSQL_URL.strip())


def _require_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if not mysql_enabled():
        raise RuntimeError("未配置 MYSQL_URL")
    from sqlalchemy import create_engine

    _ENGINE = create_engine(MYSQL_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
    return _ENGINE


@lru_cache(maxsize=1)
def _table_columns() -> set[str]:
    from sqlalchemy import inspect

    engine = _require_engine()
    insp = inspect(engine)
    return {col["name"] for col in insp.get_columns(MYSQL_TABLE)}


def _has_column(name: str) -> bool:
    try:
        return name in _table_columns()
    except Exception:
        return False


def _company_expr() -> str:
    return "COALESCE(NULLIF(TRIM(sampled_company_name), ''), NULLIF(TRIM(manufacturer_name), ''), '/')"


def _location_expr() -> str:
    parts = ["province", "city"]
    if _has_column("county"):
        parts.append("county")
    return "CONCAT_WS('', " + ", ".join(parts) + ")"


def _row_to_item(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return row_to_record(dict(mapping))


@lru_cache(maxsize=1)
def _use_fact_search() -> bool:
    from sqlalchemy import inspect

    try:
        return inspect(_require_engine()).has_table("fact_food_inspection")
    except Exception:
        return False


@lru_cache(maxsize=1)
def _use_v2_search() -> bool:
    from sqlalchemy import inspect

    try:
        return inspect(_require_engine()).has_table("inspection_base")
    except Exception:
        return False


def _status_cn(status: str) -> str:
    return "合格" if status == "qualified" else "不合格"



def _search_records_v2(
    *,
    status: str,
    province: str,
    city: str,
    county: str,
    year: str,
    date_from: str | None,
    date_to: str | None,
    company: str,
    product: str,
    category: str,
    item: str,
    reason: str,
    q: str,
    entity_role: str = "",
    page: int,
    page_size: int,
    offset: int,
    skip_total: bool = False,
) -> dict[str, Any]:
    from sqlalchemy import text

    base_where: list[str] = []
    params: dict[str, Any] = {"limit": page_size, "offset": offset}

    if status in ("qualified", "unqualified"):
        base_where.append("b.status = :status_cn")
        params["status_cn"] = _status_cn(status)

    if province and province != "全部":
        base_where.append("b.province = :province")
        params["province"] = province
    if city and city != "全部":
        base_where.append("b.city = :city")
        params["city"] = city
    if year:
        base_where.append("b.year = :year")
        params["year"] = year
    if date_from or date_to:
        from datetime import date

        start_year = date.fromisoformat(date_from).year if date_from else 2000
        end_year = date.fromisoformat(date_to).year if date_to else 2099
        base_where.append(
            "(b.year REGEXP '^[0-9]{4}$' AND CAST(b.year AS UNSIGNED) BETWEEN :year_from AND :year_to)"
        )
        params["year_from"] = start_year
        params["year_to"] = end_year

    base_where_sql = " AND ".join(base_where) if base_where else "1=1"

    extra_where: list[str] = []
    if county:
        extra_where.append(
            "(a.address LIKE :county OR a.manufacturer_address LIKE :county)"
        )
        params["county"] = f"%{county}%"
    if company:
        if entity_role == "manufacturer":
            extra_where.append("c.manufacturer LIKE :company")
        elif entity_role == "sampled":
            extra_where.append("c.sampled_company LIKE :company")
        else:
            extra_where.append(
                "(c.sampled_company LIKE :company OR c.manufacturer LIKE :company)"
            )
        params["company"] = f"%{company}%"
    if product:
        product_param = product if "%" in product else f"%{product}%"
        if status == "qualified":
            extra_where.append("(q.food_name LIKE :product OR q.sub_category LIKE :product)")
        elif status == "unqualified":
            extra_where.append("(u.food_name LIKE :product OR u.sub_category LIKE :product)")
        else:
            extra_where.append("(COALESCE(q.food_name, u.food_name) LIKE :product OR COALESCE(q.sub_category, u.sub_category) LIKE :product)")
        params["product"] = product_param
    if category:
        if status == "qualified":
            extra_where.append("q.category LIKE :category")
        elif status == "unqualified":
            extra_where.append("u.category LIKE :category")
        else:
            extra_where.append("(COALESCE(q.category, u.category) LIKE :category)")
        params["category"] = f"%{category}%"
    if item:
        extra_where.append("u.unqualified_item LIKE :item")
        params["item"] = f"%{item}%"
    if reason:
        extra_where.append(
            "(u.unqualified_reason LIKE :reason OR u.unqualified_item LIKE :reason)"
        )
        params["reason"] = f"%{reason}%"
    if q:
        like = f"%{q}%"
        params["q"] = like
        extra_where.append(
            "("
            "c.sampled_company LIKE :q OR c.manufacturer LIKE :q OR "
            "COALESCE(q.food_name, u.food_name) LIKE :q OR "
            "COALESCE(q.category, u.category) LIKE :q OR "
            "b.province LIKE :q OR b.city LIKE :q OR "
            "u.unqualified_item LIKE :q OR u.unqualified_reason LIKE :q"
            ")"
        )

    extra_where_sql = " AND ".join(extra_where)
    where_sql = base_where_sql if not extra_where_sql else f"{base_where_sql} AND {extra_where_sql}"
    has_detail_filters = bool(extra_where)

    if status == "qualified":
        detail_join = "INNER JOIN inspection_qualified q ON q.base_id = b.id"
    elif status == "unqualified":
        detail_join = "INNER JOIN inspection_unqualified u ON u.base_id = b.id"
    else:
        detail_join = """
        LEFT JOIN inspection_qualified q ON q.base_id = b.id
        LEFT JOIN inspection_unqualified u ON u.base_id = b.id
        """

    if has_detail_filters:
        join_sql = f"""
        FROM inspection_base b
        JOIN inspection_company c ON c.base_id = b.id
        LEFT JOIN inspection_address a ON a.base_id = b.id
        {detail_join}
        """
        if status == "qualified":
            food_fields = """
          q.food_name AS food_name,
          '/' AS specification,
          '/' AS trademark,
          NULL AS production_date_raw,
          '' AS unqualified_project_details,
          '' AS unqualified_item,
          '' AS unqualified_reason,
          q.category AS category,
          q.sub_category AS sub_category,
            """
        else:
            food_fields = """
          u.food_name AS food_name,
          '/' AS specification,
          '/' AS trademark,
          NULL AS production_date_raw,
          CONCAT(
            COALESCE(u.unqualified_item, ''),
            CASE
              WHEN u.standard_value <> '' OR u.test_result <> ''
                THEN CONCAT('；标准: ', u.standard_value, '；实测: ', u.test_result)
              ELSE ''
            END
          ) AS unqualified_project_details,
          COALESCE(u.unqualified_item, '') AS unqualified_item,
          CASE
            WHEN u.standard_value <> '' OR u.test_result <> ''
              THEN CONCAT('标准: ', u.standard_value, '；实测: ', u.test_result)
            ELSE ''
          END AS unqualified_reason,
          u.category AS category,
          u.sub_category AS sub_category,
            """
        select_sql = f"""
        SELECT
          b.id,
          CASE b.status WHEN '合格' THEN 'qualified' WHEN '不合格' THEN 'unqualified' ELSE b.status END AS status,
          b.province,
          b.city,
          '' AS county,
          b.year,
          b.file_source,
          b.source_sheet,
          b.batch_serial AS serial_number,
          c.manufacturer AS manufacturer_name,
          a.manufacturer_address,
          c.sampled_company AS sampled_company_name,
          a.address AS sampled_company_address,
          {food_fields}
          '' AS remarks,
          b.created_at AS created_at
        {join_sql}
        WHERE {where_sql}
        ORDER BY b.year DESC, b.id DESC
        LIMIT :limit OFFSET :offset
        """
        count_sql = f"SELECT COUNT(*) AS cnt {join_sql} WHERE {where_sql}"
    else:
        id_pick_sql = f"""
        SELECT b.id
        FROM inspection_base b
        WHERE {base_where_sql}
        ORDER BY b.year DESC, b.id DESC
        LIMIT :limit OFFSET :offset
        """
        if status == "qualified":
            food_fields = """
          q.food_name AS food_name,
          '/' AS specification,
          '/' AS trademark,
          NULL AS production_date_raw,
          '' AS unqualified_project_details,
          '' AS unqualified_item,
          '' AS unqualified_reason,
          q.category AS category,
          q.sub_category AS sub_category,
            """
        else:
            food_fields = """
          u.food_name AS food_name,
          '/' AS specification,
          '/' AS trademark,
          NULL AS production_date_raw,
          CONCAT(
            COALESCE(u.unqualified_item, ''),
            CASE
              WHEN u.standard_value <> '' OR u.test_result <> ''
                THEN CONCAT('；标准: ', u.standard_value, '；实测: ', u.test_result)
              ELSE ''
            END
          ) AS unqualified_project_details,
          COALESCE(u.unqualified_item, '') AS unqualified_item,
          CASE
            WHEN u.standard_value <> '' OR u.test_result <> ''
              THEN CONCAT('标准: ', u.standard_value, '；实测: ', u.test_result)
            ELSE ''
          END AS unqualified_reason,
          u.category AS category,
          u.sub_category AS sub_category,
            """
        select_sql = f"""
        SELECT
          b.id,
          CASE b.status WHEN '合格' THEN 'qualified' WHEN '不合格' THEN 'unqualified' ELSE b.status END AS status,
          b.province,
          b.city,
          '' AS county,
          b.year,
          b.file_source,
          b.source_sheet,
          b.batch_serial AS serial_number,
          c.manufacturer AS manufacturer_name,
          a.manufacturer_address,
          c.sampled_company AS sampled_company_name,
          a.address AS sampled_company_address,
          {food_fields}
          '' AS remarks,
          b.created_at AS created_at
        FROM inspection_base b
        JOIN ({id_pick_sql}) AS picked ON picked.id = b.id
        JOIN inspection_company c ON c.base_id = b.id
        LEFT JOIN inspection_address a ON a.base_id = b.id
        {detail_join}
        ORDER BY b.year DESC, b.id DESC
        """
        count_sql = f"SELECT COUNT(*) AS cnt FROM inspection_base b WHERE {base_where_sql}"

    engine = _require_engine()
    with engine.connect() as conn:
        if skip_total:
            total = -1
        else:
            total = int(conn.execute(text(count_sql), params).scalar() or 0)
        rows = conn.execute(text(select_sql), params).fetchall()

    items = [_row_to_item(row) for row in rows]
    total_pages = max((total + page_size - 1) // page_size, 1) if total >= 0 else None
    return {
        "items": items,
        "total": total if total >= 0 else None,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "source": "mysql_v2",
    }


def search_records(
    *,
    status: str = "qualified",
    province: str = "全部",
    city: str = "全部",
    county: str = "",
    year: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    company: str = "",
    product: str = "",
    category: str = "",
    item: str = "",
    reason: str = "",
    q: str = "",
    entity_role: str = "",
    page: int = 1,
    page_size: int = 50,
    skip_total: bool = False,
) -> dict[str, Any]:
    from food_inspection.list_data_cache import (
        get_cached_list,
        is_cacheable_list_query,
        list_cache_key,
        set_cached_list,
    )

    page = max(page, 1)
    page_size = min(max(page_size, 10), 500)
    offset = (page - 1) * page_size
    query_kwargs = dict(
        status=status,
        province=province,
        city=city,
        county=county,
        year=year,
        date_from=date_from,
        date_to=date_to,
        company=company,
        product=product,
        category=category,
        item=item,
        reason=reason,
        q=q,
        entity_role=entity_role,
        page=page,
        page_size=page_size,
        skip_total=skip_total,
    )

    if is_cacheable_list_query(**query_kwargs):
        cache_key = list_cache_key(**query_kwargs)
        cached = get_cached_list(cache_key)
        if cached:
            return cached

    if _use_fact_search():
        result = _search_records_fact(
            status=status,
            province=province,
            city=city,
            county=county,
            year=year,
            date_from=date_from,
            date_to=date_to,
            company=company,
            product=product,
            category=category,
            item=item,
            reason=reason,
            q=q,
            entity_role=entity_role,
            page=page,
            page_size=page_size,
            offset=offset,
            skip_total=skip_total,
        )
    elif _use_v2_search():
        result = _search_records_v2(
            status=status,
            province=province,
            city=city,
            county=county,
            year=year,
            date_from=date_from,
            date_to=date_to,
            company=company,
            product=product,
            category=category,
            item=item,
            reason=reason,
            q=q,
            entity_role=entity_role,
            page=page,
            page_size=page_size,
            offset=offset,
            skip_total=skip_total,
        )
    if is_cacheable_list_query(**query_kwargs):
        set_cached_list(list_cache_key(**query_kwargs), result)
    return result


def _search_records_fact(
    *,
    status: str,
    province: str,
    city: str,
    county: str,
    year: str,
    date_from: str | None,
    date_to: str | None,
    company: str,
    product: str,
    category: str,
    item: str,
    reason: str,
    q: str,
    entity_role: str,
    page: int,
    page_size: int,
    offset: int,
    skip_total: bool,
) -> dict[str, Any]:
    from sqlalchemy import text

    engine = _require_engine()
    where: list[str] = []
    params: dict[str, Any] = {"limit": page_size, "offset": offset}

    if status == "qualified":
        where.append("f.status = 1")
    elif status == "unqualified":
        where.append("f.status = 0")

    if province and province != "全部":
        where.append("f.province = :province")
        params["province"] = province
    if city and city != "全部":
        where.append("f.city = :city")
        params["city"] = city
    if county:
        where.append(
            "(f.sampled_company_address LIKE :county OR f.manufacturer_address LIKE :county)"
        )
        params["county"] = f"%{county}%"

    if year:
        where.append("f.inspection_year = :year")
        params["year"] = int(year) if year.isdigit() else year

    if date_from or date_to:
        if date_from:
            where.append("f.inspection_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            where.append("f.inspection_date <= :date_to")
            params["date_to"] = date_to

    if company:
        if entity_role == "manufacturer":
            where.append("f.manufacturer_name LIKE :company")
        elif entity_role == "sampled":
            where.append("f.sampled_company_name LIKE :company")
        else:
            where.append(
                "(f.sampled_company_name LIKE :company OR f.manufacturer_name LIKE :company)"
            )
        params["company"] = f"%{company}%"

    if product:
        product_param = product if "%" in product else f"%{product}%"
        where.append(
            "(f.food_name LIKE :product OR f.food_standard_name LIKE :product OR f.minor_category LIKE :product)"
        )
        params["product"] = product_param

    if category:
        where.append(
            "(f.minor_category LIKE :category OR f.major_category LIKE :category)"
        )
        params["category"] = f"%{category}%"

    if item:
        where.append("u.item_name LIKE :item")
        params["item"] = f"%{item}%"

    if reason:
        where.append(
            "(u.standard_value LIKE :reason OR u.measured_value LIKE :reason OR u.item_name LIKE :reason)"
        )
        params["reason"] = f"%{reason}%"

    if q:
        where.append(
            "("
            "f.food_name LIKE :q OR "
            "f.food_standard_name LIKE :q OR "
            "f.sampled_company_name LIKE :q OR "
            "f.manufacturer_name LIKE :q OR "
            "u.item_name LIKE :q"
            ")"
        )
        params["q"] = f"%{q}%"

    need_join_u = bool(item or reason or (q and "u.item_name" in "".join(where)))

    if need_join_u:
        count_from_sql = "FROM fact_food_inspection f INNER JOIN fact_unqualified_item u ON u.inspection_id = f.id"
        count_select = "SELECT COUNT(DISTINCT f.id)"
    else:
        count_from_sql = "FROM fact_food_inspection f"
        count_select = "SELECT COUNT(*)"

    if status == "qualified":
        select_cols = """
          f.id,
          f.file_id AS file_id,
          r.file_name AS source_file_name,
          r.file_path AS reg_file_path,
          'qualified' AS status,
          f.province,
          f.city,
          f.inspection_year AS year,
          f.inspection_date AS date,
          f.sampled_company_name,
          f.sampled_company_address,
          f.manufacturer_name,
          f.manufacturer_address,
          f.food_name,
          f.food_standard_name,
          f.major_category,
          f.minor_category,
          f.production_date,
          f.inspection_agency,
          f.market_supervision_bureau,
          f.created_at,
          NULL AS item_name,
          NULL AS standard_value,
          NULL AS measured_value,
          NULL AS unit
        """
        select_from_sql = "FROM fact_food_inspection f LEFT JOIN file_registry r ON r.id = f.file_id"
    else:
        select_cols = """
          f.id,
          f.file_id AS file_id,
          r.file_name AS source_file_name,
          r.file_path AS reg_file_path,
          CASE f.status WHEN 1 THEN 'qualified' WHEN 0 THEN 'unqualified' ELSE CAST(f.status AS CHAR) END AS status,
          f.province,
          f.city,
          f.inspection_year AS year,
          f.inspection_date AS date,
          f.sampled_company_name,
          f.sampled_company_address,
          f.manufacturer_name,
          f.manufacturer_address,
          f.food_name,
          f.food_standard_name,
          f.major_category,
          f.minor_category,
          f.production_date,
          f.inspection_agency,
          f.market_supervision_bureau,
          f.created_at,
          u.item_name,
          u.standard_value,
          u.measured_value,
          u.unit
        """
        if need_join_u:
            select_from_sql = "FROM fact_food_inspection f LEFT JOIN file_registry r ON r.id = f.file_id INNER JOIN fact_unqualified_item u ON u.inspection_id = f.id"
        else:
            select_from_sql = "FROM fact_food_inspection f LEFT JOIN file_registry r ON r.id = f.file_id LEFT JOIN fact_unqualified_item u ON u.inspection_id = f.id"

    where_sql = " AND ".join(where) if where else "1=1"

    count_sql = f"{count_select} {count_from_sql} WHERE {where_sql}"

    select_sql = f"""
    SELECT {select_cols} {select_from_sql} WHERE {where_sql} ORDER BY f.id DESC LIMIT :limit OFFSET :offset
    """

    with engine.connect() as conn:
        if skip_total:
            total = -1
        else:
            total = int(conn.execute(text(count_sql), params).scalar() or 0)
        rows = conn.execute(text(select_sql), params).fetchall()

        item_breakdown = []
        if status == "unqualified" and total != 0:
            breakdown_sql = f"""
            SELECT u.item_name AS item, COUNT(*) AS count
            FROM fact_unqualified_item u
            JOIN fact_food_inspection f ON u.inspection_id = f.id
            WHERE {where_sql} AND u.item_name IS NOT NULL AND u.item_name <> ''
            GROUP BY u.item_name
            ORDER BY count DESC
            LIMIT 50
            """
            try:
                bd_rows = conn.execute(text(breakdown_sql), params).fetchall()
                item_breakdown = [{"item": row[0], "count": int(row[1])} for row in bd_rows]
            except Exception:
                item_breakdown = []

    items = [_row_to_item(row) for row in rows]
    total_pages = max((total + page_size - 1) // page_size, 1) if total >= 0 else None
    return {
        "items": items,
        "total": total if total >= 0 else None,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "item_breakdown": item_breakdown,
        "source": "mysql",
    }



def _search_records_legacy(
    *,
    status: str,
    province: str,
    city: str,
    county: str,
    year: str,
    date_from: str | None,
    date_to: str | None,
    company: str,
    product: str,
    category: str,
    item: str,
    reason: str,
    q: str,
    entity_role: str,
    page: int,
    page_size: int,
    offset: int,
    skip_total: bool,
) -> dict[str, Any]:

    from sqlalchemy import text

    engine = _require_engine()

    where: list[str] = []
    params: dict[str, Any] = {"limit": page_size, "offset": offset}

    if status == "qualified":
        where.append("(status = 1 OR status = '1' OR status = '合格')")
    elif status == "unqualified":
        where.append("(status = 0 OR status = '0' OR status = '不合格')")

    if province and province != "全部":
        where.append("province = :province")
        params["province"] = province
    if city and city != "全部":
        where.append("city = :city")
        params["city"] = city
    if county and _has_column("county"):
        where.append(
            "(county LIKE :county OR sampled_company_address LIKE :county "
            "OR manufacturer_address LIKE :county)"
        )
        params["county"] = f"%{county}%"
    if year:
        if _has_column("year"):
            where.append("year = :year")
        elif _has_column("date"):
            where.append("date LIKE :year_like")
            params["year_like"] = f"{year}%"
        params["year"] = year
    if date_from or date_to:
        from datetime import date

        start_year = date.fromisoformat(date_from).year if date_from else 2000
        end_year = date.fromisoformat(date_to).year if date_to else 2099
        if _has_column("year"):
            where.append(
                "(year REGEXP '^[0-9]{4}$' AND CAST(year AS UNSIGNED) BETWEEN :year_from AND :year_to)"
            )
            params["year_from"] = start_year
            params["year_to"] = end_year
        elif _has_column("date"):
            where.append("date BETWEEN :date_from AND :date_to")
            params["date_from"] = date_from or f"{start_year}-01-01"
            params["date_to"] = date_to or f"{end_year}-12-31"

    if company:
        if entity_role == "manufacturer" and _has_column("manufacturer_name"):
            where.append("manufacturer_name LIKE :company")
        elif entity_role == "sampled" and _has_column("sampled_company_name"):
            where.append("sampled_company_name LIKE :company")
        else:
            where.append(f"{_company_expr()} LIKE :company")
        params["company"] = f"%{company}%"
    if product:
        where.append("food_name LIKE :product")
        params["product"] = f"%{product}%"
    if category:
        where.append("category LIKE :category")
        params["category"] = f"%{category}%"
    if item and _has_column("unqualified_item"):
        where.append("unqualified_item LIKE :item")
        params["item"] = f"%{item}%"
    elif item:
        where.append("unqualified_project_details LIKE :item")
        params["item"] = f"%{item}%"
    if reason and _has_column("unqualified_reason"):
        where.append("unqualified_reason LIKE :reason")
        params["reason"] = f"%{reason}%"
    elif reason:
        where.append("unqualified_project_details LIKE :reason")
        params["reason"] = f"%{reason}%"

    if q:
        like = f"%{q}%"
        params["q"] = like
        q_parts = [
            f"{_company_expr()} LIKE :q",
            "food_name LIKE :q",
            "category LIKE :q",
            "province LIKE :q",
            "city LIKE :q",
        ]
        if _has_column("county"):
            q_parts.append("county LIKE :q")
        if _has_column("unqualified_item"):
            q_parts.extend(["unqualified_item LIKE :q", "unqualified_reason LIKE :q"])
        else:
            q_parts.append("unqualified_project_details LIKE :q")
        where.append("(" + " OR ".join(q_parts) + ")")

    where_sql = " AND ".join(where) if where else "1=1"
    table = MYSQL_TABLE
    print(f"[DEBUG table check] table={repr(table)} matches={table == 'fact_food_inspection'}", flush=True)

    if table == "fact_food_inspection":
        # Prefix columns in where_sql to avoid ambiguity with file_registry
        f_where_sql = (
            where_sql.replace("status =", f"`{table}`.status =")
            .replace("province =", f"`{table}`.province =")
            .replace("city =", f"`{table}`.city =")
            .replace("county LIKE", f"`{table}`.county LIKE")
            .replace("sampled_company_address LIKE", f"`{table}`.sampled_company_address LIKE")
            .replace("manufacturer_address LIKE", f"`{table}`.manufacturer_address LIKE")
            .replace("sampled_company_name LIKE", f"`{table}`.sampled_company_name LIKE")
            .replace("manufacturer_name LIKE", f"`{table}`.manufacturer_name LIKE")
            .replace("food_name LIKE", f"`{table}`.food_name LIKE")
            .replace("category LIKE", f"`{table}`.category LIKE")
        )
        count_sql = f"SELECT COUNT(*) AS cnt FROM `{table}` WHERE {f_where_sql}"
        data_sql = (
            f"SELECT `{table}`.*, reg.file_path AS reg_file_path FROM `{table}` "
            f"LEFT JOIN file_registry reg ON reg.id = `{table}`.file_id "
            f"WHERE {f_where_sql} "
            f"ORDER BY `{table}`.id DESC LIMIT :limit OFFSET :offset"
        )
    else:
        count_sql = f"SELECT COUNT(*) AS cnt FROM `{table}` WHERE {where_sql}"
        order_cols = []
        if _has_column("date"):
            order_cols.append("date DESC")
        elif _has_column("year"):
            order_cols.append("year DESC")
        if _has_column("id"):
            order_cols.append("id DESC")
        else:
            order_cols.append("1 DESC")
        data_sql = (
            f"SELECT * FROM `{table}` WHERE {where_sql} "
            f"ORDER BY {', '.join(order_cols)} LIMIT :limit OFFSET :offset"
        )

    with engine.connect() as conn:
        if skip_total:
            total = -1
        else:
            total = int(conn.execute(text(count_sql), params).scalar() or 0)
        rows = conn.execute(text(data_sql), params).fetchall()
        if rows:
            print("[DEBUG _search_records_fact] data_sql:", data_sql, flush=True)
            print("[DEBUG _search_records_fact] row 0 mapping:", dict(rows[0]._mapping), flush=True)

    items = [_row_to_item(row) for row in rows]
    total_pages = max((total + page_size - 1) // page_size, 1) if total >= 0 else None
    return {
        "items": items,
        "total": total if total >= 0 else None,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "source": "mysql",
    }


def _is_plausible_county(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if any(k in name for k in ("镇", "村", "街", "路", "社区", "小区", "市场", "农贸", "办事")):
        return False
    return True


def extract_county_from_address(address: str, city: str = "") -> str:
    """从地址提取区县/县级市名（优先取「XX市」之后的第一个行政区划）。"""
    text = re.sub(r"\s+", "", (address or "").strip())
    if not text:
        return ""
    city_key = re.sub(r"\s+", "", city)

    head = re.match(r"([\u4e00-\u9fa5]{2,8}(?:区|县|市))", text)
    if head:
        name = head.group(1)
        if _is_plausible_county(name) and name != city_key and not name.endswith("州市"):
            return name

    if city_key and city_key in text:
        rest = text.split(city_key, 1)[-1]
        match = re.match(r"([\u4e00-\u9fa5]{2,8}(?:区|县|市))", rest)
        if match:
            name = match.group(1)
            if _is_plausible_county(name) and name != city_key:
                return name

    for match in re.finditer(r"市([\u4e00-\u9fa5]{2,8}(?:区|县))", text):
        name = match.group(1)
        if _is_plausible_county(name):
            return name

    for match in re.finditer(r"市([\u4e00-\u9fa5]{2,8}市)", text):
        name = match.group(1)
        if city_key and name == city_key:
            continue
        if name.endswith("州市"):
            continue
        if _is_plausible_county(name):
            return name

    return ""
