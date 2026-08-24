"""MySQL 数据源 — shipin.food_inspection_records"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import date
from typing import Any

from config import DATA_ROOT, MYSQL_DATABASE, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_TABLE, MYSQL_USER
from food_inspection.parser.fields import sanitize_product_name
from food_inspection.parser.text import (
    collapse_wrapped_chinese_text,
    normalize_company_name,
    normalize_product_name,
)

_COMPANY_SQL = (
    "COALESCE(NULLIF(TRIM(sampled_company_name), ''), NULLIF(TRIM(manufacturer_name), ''), '')"
)
_SAMPLED_COMPANY_SQL = "NULLIF(TRIM(sampled_company_name), '')"
_MANUFACTURER_SQL = "NULLIF(TRIM(manufacturer_name), '')"
_REASON_SQL = (
    "COALESCE(NULLIF(TRIM(standard_unqualified_item), ''), NULLIF(TRIM(unqualified_project_details), ''), '')"
)

_year_re = re.compile(r"^20\d{2}$")


def mysql_enabled() -> bool:
    from config import USE_MYSQL

    return USE_MYSQL


def ping() -> bool:
    if not mysql_enabled():
        return False
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


@contextmanager
def connection():
    import pymysql

    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=120,
        write_timeout=120,
    )
    try:
        yield conn
    finally:
        conn.close()


def _years_from_date_range(date_from: str | None, date_to: str | None) -> list[str] | None:
    if not date_from and not date_to:
        return None
    start = date.fromisoformat(date_from) if date_from else date(2000, 1, 1)
    end = date.fromisoformat(date_to) if date_to else date(2099, 12, 31)
    years = [str(y) for y in range(start.year, end.year + 1)]
    return years


def _parse_path_location(file_source: str) -> tuple[str, str]:
    parts = (file_source or "").replace("\\", "/").split("/")
    parts = [p for p in parts if p]
    province = parts[0] if parts else ""
    city = ""
    if len(parts) > 1 and not _year_re.fullmatch(parts[1]):
        city = parts[1]
    elif len(parts) > 2:
        city = parts[2] if not _year_re.fullmatch(parts[2]) else ""
    return province, city


def resolve_disk_path(file_source: str) -> str:
    """将库内相对路径、file_id 或 UNC 网络路径转为磁盘上的绝对路径。"""
    raw = (file_source or "").strip()
    if not raw:
        return ""

    if str(raw).isdigit():
        try:
            with connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT file_path, file_path_key FROM file_registry WHERE id = %s LIMIT 1",
                    (int(raw),),
                )
                row = cur.fetchone()
                if row:
                    raw = row.get("file_path") or row.get("file_path_key") or ""
        except Exception:
            pass

    clean = str(raw).replace("\\", "/").strip()
    idx = clean.find("全国各省市食品安全监督抽查")
    if idx != -1:
        rel = clean[idx + len("全国各省市食品安全监督抽查"):].lstrip("/")
        local_path = os.path.normpath(os.path.join(DATA_ROOT, rel))
        if os.path.isfile(local_path):
            return local_path
        return local_path

    if os.path.isabs(clean) and os.path.isfile(clean):
        return os.path.normpath(clean)

    joined = os.path.normpath(os.path.join(DATA_ROOT, clean.lstrip("/")))
    if os.path.isfile(joined):
        return joined

    return os.path.normpath(clean) if clean else ""


def row_to_analytics_record(row: dict[str, Any]) -> dict[str, Any]:
    """Analytics 专用：跳过磁盘 path 探测，减少百万级 os.path.isfile 开销。"""
    file_source = (row.get("file_source") or "").strip()
    province = (row.get("province") or "").strip()
    city = (row.get("city") or "").strip()
    source_province, source_city = _parse_path_location(file_source)
    if not source_province:
        source_province = province
    if not source_city:
        source_city = city
    sampled = normalize_company_name(row.get("sampled_company_name") or "")
    manufacturer = normalize_company_name(row.get("manufacturer_name") or "")
    product = sanitize_product_name(row.get("food_name") or row.get("food_standard_name") or "")
    sub_category = (row.get("minor_category") or row.get("sub_category") or "").strip()
    major_category = (row.get("major_category") or row.get("category") or "").strip()

    raw_status = row.get("status")
    if raw_status in (1, "1", "合格"):
        status_str = "qualified"
    elif raw_status in (0, "0", "不合格"):
        status_str = "unqualified"
    else:
        status_str = str(raw_status or "")

    item_name = (row.get("item_name") or row.get("standard_unqualified_items") or row.get("unqualified_item") or "").strip()
    measured = (row.get("measured_value") or "").strip()
    std_val = (row.get("standard_value") or row.get("standar_value") or "").strip()
    unit = (row.get("unit") or "").strip()

    if measured or std_val:
        reason_str = f"标准: {std_val}；实测: {measured}{unit}"
    else:
        reason_str = (row.get("unqualified_reason") or row.get("unqualified_project_details") or "").strip()

    year_str = str(row.get("inspection_year") or row.get("year") or "").strip()

    return {
        "status": status_str,
        "company": sampled,
        "sampled_company": sampled,
        "manufacturer": manufacturer,
        "product": product,
        "sub_category": sub_category,
        "province": province,
        "city": city,
        "unqualified_item": item_name,
        "standard_unqualified_item": item_name,
        "measured_value": measured,
        "standar_value": std_val,
        "standard_value": std_val,
        "unit": unit,
        "unqualified_project_details": f"{item_name} ({reason_str})" if item_name and reason_str else (item_name or reason_str),
        "reason": reason_str,
        "unqualified_reason": reason_str,
        "category": sub_category or major_category,
        "major_category": major_category,
        "minor_category": sub_category,
        "source_file": file_source,
        "source_province": source_province,
        "source_city": source_city,
        "year": year_str,
    }


def row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    file_source = (row.get("reg_file_path") or row.get("file_source") or str(row.get("file_id") or "")).strip()
    province = (row.get("province") or "").strip()
    city = (row.get("city") or "").strip()
    source_province, source_city = _parse_path_location(file_source)
    if not source_province:
        source_province = province
    if not source_city:
        source_city = city
    disk_path = resolve_disk_path(file_source)
    sampled = normalize_company_name(row.get("sampled_company_name") or "")
    manufacturer = normalize_company_name(row.get("manufacturer_name") or "")
    product = sanitize_product_name(row.get("food_name") or row.get("food_standard_name") or "")
    sub_category = (row.get("minor_category") or row.get("sub_category") or "").strip()
    major_category = (row.get("major_category") or row.get("category") or "").strip()

    raw_status = row.get("status")
    if raw_status in (1, "1", "合格"):
        status_str = "qualified"
    elif raw_status in (0, "0", "不合格"):
        status_str = "unqualified"
    else:
        status_str = str(raw_status or "")

    item_name = (row.get("item_name") or row.get("unqualified_item") or row.get("standard_unqualified_items") or "").strip()
    measured = (row.get("measured_value") or "").strip()
    std_val = (row.get("standard_value") or row.get("standar_value") or "").strip()
    unit = (row.get("unit") or "").strip()

    if measured or std_val:
        reason_str = f"标准: {std_val}；实测: {measured}{unit}"
    else:
        reason_str = (row.get("unqualified_reason") or row.get("unqualified_project_details") or "").strip()

    if item_name and reason_str:
        unqualified_details = f"{item_name} ({reason_str})"
    else:
        unqualified_details = item_name or reason_str

    province_city = f"{province} / {city}" if province and city else province or city
    year_str = str(row.get("inspection_year") or row.get("year") or "").strip()
    date_str = str(row.get("inspection_date") or row.get("date") or "").strip()

    return {
        "id": row.get("id"),
        "status": status_str,
        "company": sampled,
        "sampled_company": sampled,
        "manufacturer": manufacturer,
        "product": product,
        "sub_category": sub_category,
        "province": province,
        "city": city,
        "province_city": province_city,
        "unqualified_item": item_name,
        "standard_unqualified_item": item_name,
        "measured_value": measured,
        "standar_value": std_val,
        "standard_value": std_val,
        "unit": unit,
        "unqualified_project_details": unqualified_details,
        "reason": reason_str,
        "unqualified_reason": reason_str,
        "category": sub_category or major_category,
        "major_category": major_category,
        "minor_category": sub_category,
        "source_file": disk_path or file_source,
        "file_source": disk_path or file_source,
        "file_id": row.get("file_id"),
        "source_file_name": os.path.basename(file_source.replace("\\", "/")) if file_source else "",
        "source_sheet": (row.get("source_sheet") or "").strip(),
        "source_province": source_province,
        "source_city": source_city,
        "year": year_str,
        "date": date_str,
        "file_source": file_source,
        "sampled_company_address": collapse_wrapped_chinese_text(row.get("sampled_company_address") or ""),
        "manufacturer_address": collapse_wrapped_chinese_text(row.get("manufacturer_address") or ""),
    }


def _build_where(
    *,
    status: str,
    province: str,
    city: str,
    company: str,
    product: str,
    item: str,
    category: str,
    keyword: str,
    date_from: str | None,
    date_to: str | None,
    mapped_only: bool = False,
    prefix: str = "",
) -> tuple[str, list[Any]]:
    col_status = f"{prefix}status" if prefix else "status"
    col_prov = f"{prefix}province" if prefix else "province"
    col_city = f"{prefix}city" if prefix else "city"
    col_year = f"{prefix}inspection_year" if prefix else "inspection_year"
    col_minor = f"{prefix}minor_category" if prefix else "minor_category"
    col_major = f"{prefix}major_category" if prefix else "major_category"
    col_food = f"{prefix}food_name" if prefix else "food_name"
    col_food_std = f"{prefix}food_standard_name" if prefix else "food_standard_name"
    col_sampled = f"{prefix}sampled_company_name" if prefix else "sampled_company_name"
    col_mfg = f"{prefix}manufacturer_name" if prefix else "manufacturer_name"

    clauses: list[str] = []
    params: list[Any] = []

    if status == "qualified":
        clauses.append(f"({col_status} = 1 OR {col_status} = '合格')")
    elif status == "unqualified":
        clauses.append(f"({col_status} = 0 OR {col_status} = '不合格')")
    elif status:
        clauses.append(f"{col_status} = %s")
        params.append(status)

    if province and province != "全部":
        clauses.append(f"{col_prov} = %s")
        params.append(province)
    if city and city != "全部":
        clauses.append(f"{col_city} = %s")
        params.append(city)

    years = _years_from_date_range(date_from, date_to)
    if years is not None:
        placeholders = ", ".join(["%s"] * len(years))
        clauses.append(f"{col_year} IN ({placeholders})")
        params.extend(years)

    if company:
        like = f"%{company}%"
        clauses.append(f"({col_sampled} LIKE %s OR {col_mfg} LIKE %s)")
        params.extend([like, like])
    if product:
        like = f"%{product}%"
        clauses.append(f"({col_food} LIKE %s OR {col_food_std} LIKE %s)")
        params.extend([like, like])
    if item:
        clauses.append(f"{col_minor} LIKE %s")
        params.append(f"%{item}%")
    if category:
        like = f"%{category}%"
        clauses.append(f"({col_major} LIKE %s OR {col_minor} LIKE %s)")
        params.extend([like, like])

    if mapped_only:
        clauses.append(f"TRIM(COALESCE({col_minor}, '')) <> ''")

    if keyword and not any((company, product, item, category)):
        like = f"%{keyword}%"
        clauses.append(
            "("
            f"{col_sampled} LIKE %s OR {col_mfg} LIKE %s OR {col_food} LIKE %s OR {col_food_std} LIKE %s "
            f"OR {col_prov} LIKE %s OR {col_city} LIKE %s OR {col_minor} LIKE %s OR {col_major} LIKE %s"
            ")"
        )
        params.extend([like] * 8)

    return " AND ".join(clauses), params


def _build_scope_where(
    *,
    province: str,
    city: str,
    date_from: str | None,
    date_to: str | None,
    mapped_only: bool = False,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if province and province != "全部":
        clauses.append("province = %s")
        params.append(province)
    if city and city != "全部":
        clauses.append("city = %s")
        params.append(city)

    years = _years_from_date_range(date_from, date_to)
    if years is not None:
        placeholders = ", ".join(["%s"] * len(years))
        clauses.append(f"inspection_year IN ({placeholders})")
        params.extend(years)

    if mapped_only:
        clauses.append("TRIM(COALESCE(minor_category, '')) <> ''")

    if clauses:
        return " AND ".join(clauses), params
    return "1=1", params


def _rows_to_status_counter(
    rows: list[dict[str, Any]],
    *,
    name_key: str,
    normalize_name=None,
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        raw_name = (row.get(name_key) or "").strip()
        if not raw_name:
            continue
        name = normalize_name(raw_name) if normalize_name else raw_name
        if not name:
            continue
        bucket = out.setdefault(name, {"qualified": 0, "unqualified": 0})
        status = row.get("status")
        if status is None:
            status = ""
        cnt = int(row.get("cnt") or 0)
        if status in ("qualified", "合格", "1", 1):
            bucket["qualified"] += cnt
        elif status in ("unqualified", "不合格", "0", 0):
            bucket["unqualified"] += cnt
    return out


def _rows_to_company_top_products(
    rows: list[dict[str, Any]],
    *,
    name_key: str,
    product_key: str = "food_name",
    normalize_name=None,
    normalize_product=None,
    per_company_limit: int = 8,
) -> dict[str, list[str]]:
    from collections import Counter, defaultdict

    counters: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        raw_name = (row.get(name_key) or "").strip()
        raw_product = (row.get(product_key) or "").strip()
        if not raw_name or not raw_product:
            continue
        name = normalize_name(raw_name) if normalize_name else raw_name
        product = normalize_product(raw_product) if normalize_product else raw_product
        if not name or not product:
            continue
        counters[name][product] += int(row.get("cnt") or 0)

    return {
        company: [product for product, _ in counter.most_common(per_company_limit)]
        for company, counter in counters.items()
    }


def fetch_analytics_sql_aggregates(
    *,
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
    parallel: bool = True,
) -> dict[str, Any]:
    """SQL 聚合合格/不合格计数，避免拉取百万级合格明细。"""
    from concurrent.futures import ThreadPoolExecutor

    where, params = _build_scope_where(
        province=province,
        city=city,
        date_from=date_from,
        date_to=date_to,
        mapped_only=True,
    )
    table = MYSQL_TABLE

    def _run_product_query() -> dict[str, dict[str, int]]:
        from food_inspection.analytics import canonical_tableware_product_name

        # 榜单统计按食品小类(minor_category)聚合
        sql = f"""
            SELECT TRIM(minor_category) AS product_name, status, COUNT(*) AS cnt
            FROM `{table}`
            WHERE {where}
              AND minor_category IS NOT NULL AND TRIM(minor_category) <> ''
            GROUP BY TRIM(minor_category), status
        """
        with connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return _rows_to_status_counter(
                cur.fetchall(),
                name_key="product_name",
                normalize_name=lambda name: canonical_tableware_product_name((name or "").strip()),
            )

    def _run_sampled_query() -> dict[str, dict[str, int]]:
        sql = f"""
            SELECT TRIM(sampled_company_name) AS company_name, status, COUNT(*) AS cnt
            FROM `{table}`
            WHERE {where}
              AND sampled_company_name IS NOT NULL AND TRIM(sampled_company_name) <> ''
            GROUP BY TRIM(sampled_company_name), status
        """
        with connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return _rows_to_status_counter(cur.fetchall(), name_key="company_name", normalize_name=normalize_company_name)

    def _run_manufacturer_query() -> dict[str, dict[str, int]]:
        sql = f"""
            SELECT TRIM(manufacturer_name) AS company_name, status, COUNT(*) AS cnt
            FROM `{table}`
            WHERE {where}
              AND manufacturer_name IS NOT NULL AND TRIM(manufacturer_name) <> ''
            GROUP BY TRIM(manufacturer_name), status
        """
        with connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return _rows_to_status_counter(cur.fetchall(), name_key="company_name", normalize_name=normalize_company_name)

    def _run_city_query() -> dict[str, dict[str, int]]:
        sql = f"""
            SELECT province, city, status, COUNT(*) AS cnt
            FROM `{table}`
            WHERE {where}
              AND city IS NOT NULL AND TRIM(city) <> ''
            GROUP BY province, city, status
        """
        cities: dict[str, dict[str, int]] = {}
        with connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            for row in cur.fetchall():
                prov = (row.get("province") or "").strip()
                city_name = (row.get("city") or "").strip()
                if not city_name:
                    continue
                if province and province != "全部":
                    city_key = city_name
                elif prov:
                    city_key = f"{prov} / {city_name}"
                else:
                    city_key = city_name
                bucket = cities.setdefault(city_key, {"qualified": 0, "unqualified": 0})
                status = row.get("status")
                if status is None:
                    status = ""
                cnt = int(row.get("cnt") or 0)
                if status in ("qualified", "合格", "1", 1):
                    bucket["qualified"] += cnt
                elif status in ("unqualified", "不合格", "0", 0):
                    bucket["unqualified"] += cnt
        return cities

    if parallel:
        with ThreadPoolExecutor(max_workers=4) as pool:
            products_f = pool.submit(_run_product_query)
            sampled_f = pool.submit(_run_sampled_query)
            manufacturer_f = pool.submit(_run_manufacturer_query)
            cities_f = pool.submit(_run_city_query)
            return {
                "products": products_f.result(),
                "sampled_companies": sampled_f.result(),
                "manufacturers": manufacturer_f.result(),
                "cities": cities_f.result(),
            }

    return {
        "products": _run_product_query(),
        "sampled_companies": _run_sampled_query(),
        "manufacturers": _run_manufacturer_query(),
        "cities": _run_city_query(),
    }


def fetch_product_batch_totals_for_names(
    product_names: list[str],
    *,
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, dict[str, int]]:
    """按产品名列表快速汇总抽检批次数（用于高频违规产品总数）。"""
    from food_inspection.parser.fields import sanitize_product_name

    names = [sanitize_product_name(n) for n in product_names if (n or "").strip()]
    names = sorted({n for n in names if n})
    if not names:
        return {}

    where, params = _build_scope_where(
        province=province,
        city=city,
        date_from=date_from,
        date_to=date_to,
    )
    placeholders = ", ".join(["%s"] * len(names))
    table = MYSQL_TABLE
    sql = f"""
        SELECT TRIM(food_name) AS food_name, status, COUNT(*) AS cnt
        FROM `{table}`
        WHERE {where}
          AND TRIM(food_name) IN ({placeholders})
        GROUP BY TRIM(food_name), status
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, [*params, *names])
        raw = _rows_to_status_counter(
            cur.fetchall(), name_key="food_name", normalize_name=sanitize_product_name
        )
    out: dict[str, dict[str, int]] = {}
    for name, counts in raw.items():
        qualified = int(counts.get("qualified") or 0)
        unqualified = int(counts.get("unqualified") or 0)
        total = qualified + unqualified
        if total <= 0:
            continue
        out[name] = {
            "qualified": qualified,
            "unqualified": unqualified,
            "total_count": total,
        }
    return out


def fetch_product_batch_totals_map(
    *,
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, dict[str, int]]:
    """按归一化产品名汇总合格/不合格批次数（用于高频违规产品抽检总数）。"""
    from food_inspection.parser.fields import sanitize_product_name

    where, params = _build_scope_where(
        province=province,
        city=city,
        date_from=date_from,
        date_to=date_to,
    )
    table = MYSQL_TABLE
    sql = f"""
        SELECT TRIM(food_name) AS food_name, status, COUNT(*) AS cnt
        FROM `{table}`
        WHERE {where}
          AND food_name IS NOT NULL AND TRIM(food_name) <> ''
        GROUP BY TRIM(food_name), status
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        raw = _rows_to_status_counter(
            cur.fetchall(), name_key="food_name", normalize_name=sanitize_product_name
        )
    out: dict[str, dict[str, int]] = {}
    for name, counts in raw.items():
        qualified = int(counts.get("qualified") or 0)
        unqualified = int(counts.get("unqualified") or 0)
        total = qualified + unqualified
        if total <= 0:
            continue
        out[name] = {
            "qualified": qualified,
            "unqualified": unqualified,
            "total_count": total,
        }
    return out


def fetch_company_top_products(
    company_names: list[str],
    *,
    company_column: str = "sampled_company_name",
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
    per_company_limit: int = 8,
) -> dict[str, list[str]]:
    """按单位名称批量查询合格产品 Top N（供绿榜展示）。"""
    names = [normalize_company_name(n) for n in company_names if (n or "").strip()]
    names = [n for n in names if n]
    if not names:
        return {}

    where, params = _build_scope_where(
        province=province,
        city=city,
        date_from=date_from,
        date_to=date_to,
    )
    table = MYSQL_TABLE
    col = company_column.strip()
    if col not in ("sampled_company_name", "manufacturer_name"):
        return {}

    all_rows: list[dict[str, Any]] = []
    chunk_size = 200
    with connection() as conn, conn.cursor() as cur:
        for start in range(0, len(names), chunk_size):
            chunk = names[start : start + chunk_size]
            placeholders = ", ".join(["%s"] * len(chunk))
            sql = f"""
                SELECT TRIM({col}) AS company_name,
                       TRIM(food_name) AS food_name,
                       COUNT(*) AS cnt
                FROM `{table}`
                WHERE {where}
                  AND status = 'qualified'
                  AND TRIM({col}) IN ({placeholders})
                  AND food_name IS NOT NULL AND TRIM(food_name) <> ''
                GROUP BY TRIM({col}), TRIM(food_name)
            """
            cur.execute(sql, [*params, *chunk])
            all_rows.extend(cur.fetchall())

    return _rows_to_company_top_products(
        all_rows,
        name_key="company_name",
        normalize_name=normalize_company_name,
        normalize_product=sanitize_product_name,
        per_company_limit=per_company_limit,
    )


def query_records(
    *,
    status: str,
    province: str = "全部",
    city: str = "全部",
    company: str = "",
    product: str = "",
    item: str = "",
    category: str = "",
    keyword: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    where, params = _build_where(
        status=status,
        province=province,
        city=city,
        company=company.lower(),
        product=product.lower(),
        item=item.lower(),
        category=category.lower(),
        keyword=keyword.lower(),
        date_from=date_from,
        date_to=date_to,
    )
    table = MYSQL_TABLE
    offset = (max(page, 1) - 1) * page_size

    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM `{table}` WHERE {where}", params)
        total = int(cur.fetchone()["cnt"])
        cur.execute(
            f"SELECT * FROM `{table}` WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s",
            [*params, page_size, offset],
        )
        rows = cur.fetchall()

    return {
        "items": [row_to_record(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


def list_provinces() -> list[str]:
    table = MYSQL_TABLE
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT province FROM `{table}` "
            "WHERE province IS NOT NULL AND province <> '' ORDER BY province"
        )
        return [r["province"] for r in cur.fetchall()]


def list_cities(province: str = "全部") -> list[str]:
    table = MYSQL_TABLE
    with connection() as conn, conn.cursor() as cur:
        if province and province != "全部":
            cur.execute(
                f"SELECT DISTINCT city FROM `{table}` "
                "WHERE province = %s AND city IS NOT NULL AND city <> '' ORDER BY city",
                (province,),
            )
        else:
            cur.execute(
                f"SELECT DISTINCT city FROM `{table}` "
                "WHERE city IS NOT NULL AND city <> '' ORDER BY city"
            )
        return [r["city"] for r in cur.fetchall()]


def summary_stats() -> dict[str, Any]:
    table = MYSQL_TABLE
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT status, COUNT(*) AS cnt FROM `{table}` GROUP BY status"
        )
        by_status = {r["status"]: int(r["cnt"]) for r in cur.fetchall()}
        cur.execute(
            f"SELECT province, COUNT(*) AS cnt FROM `{table}` "
            "WHERE province <> '' GROUP BY province"
        )
        provinces = {r["province"]: int(r["cnt"]) for r in cur.fetchall()}
        cur.execute(f"SELECT COUNT(DISTINCT file_source) AS cnt FROM `{table}`")
        file_count = int(cur.fetchone()["cnt"])

    qualified = by_status.get("qualified", 0)
    unqualified = by_status.get("unqualified", 0)
    return {
        "qualified_count": qualified,
        "unqualified_count": unqualified,
        "total_files": file_count,
        "parsed_files": file_count,
        "provinces": provinces,
        "count_mode": "item",
        "data_source": "mysql",
        "mysql_database": MYSQL_DATABASE,
        "mysql_table": MYSQL_TABLE,
    }


def company_stats(
    keyword: str,
    *,
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []

    clauses = [f"({_SAMPLED_COMPANY_SQL} LIKE %s OR {_MANUFACTURER_SQL} LIKE %s)"]
    params: list[Any] = [f"%{keyword}%", f"%{keyword}%"]

    if province and province != "全部":
        clauses.append("province = %s")
        params.append(province)
    if city and city != "全部":
        clauses.append("city = %s")
        params.append(city)

    years = _years_from_date_range(date_from, date_to)
    if years is not None:
        placeholders = ", ".join(["%s"] * len(years))
        clauses.append(f"year IN ({placeholders})")
        params.extend(years)

    where = " AND ".join(clauses)
    table = MYSQL_TABLE
    sql = f"""
        SELECT
            sampled_company_name AS sampled_company,
            manufacturer_name AS manufacturer,
            SUM(status = 'qualified') AS qualified_count,
            SUM(status = 'unqualified') AS unqualified_count,
            COUNT(*) AS total_count,
            GROUP_CONCAT(DISTINCT food_name ORDER BY food_name SEPARATOR '||') AS products_raw,
            GROUP_CONCAT(DISTINCT city ORDER BY city SEPARATOR '||') AS cities_raw
        FROM `{table}`
        WHERE {where}
        GROUP BY sampled_company_name, manufacturer_name
        HAVING sampled_company_name <> '' OR manufacturer_name <> ''
        ORDER BY total_count DESC, unqualified_count DESC
        LIMIT %s
    """
    params.append(limit)

    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        total = int(row["total_count"] or 0)
        unqualified = int(row["unqualified_count"] or 0)
        products = [p for p in (row.get("products_raw") or "").split("||") if p][:6]
        cities = [c for c in (row.get("cities_raw") or "").split("||") if c][:6]
        items.append(
            {
                "company": (row.get("sampled_company") or row.get("manufacturer") or "").strip(),
                "sampled_company": (row.get("sampled_company") or "").strip(),
                "manufacturer": (row.get("manufacturer") or "").strip(),
                "qualified_count": int(row["qualified_count"] or 0),
                "unqualified_count": unqualified,
                "total_count": total,
                "failure_rate": round(unqualified / total * 100, 2) if total else 0,
                "products": products,
                "cities": cities,
            }
        )
    return items


_ANALYTICS_SELECT = """
    SELECT
        f.status,
        COALESCE(NULLIF(TRIM(f.food_standard_name), ''), NULLIF(TRIM(f.food_name), ''), '') AS food_name,
        f.sampled_company_name,
        f.manufacturer_name,
        f.sampled_company_address,
        f.manufacturer_address,
        f.province,
        f.city,
        f.major_category,
        f.minor_category,
        f.inspection_year,
        f.inspection_date,
        u.item_name AS unqualified_item,
        u.item_name AS standard_unqualified_item,
        u.measured_value,
        u.standard_value AS standar_value,
        u.standard_value,
        u.unit
    FROM `{table}` f
    LEFT JOIN `fact_unqualified_item` u ON u.inspection_id = f.id
    WHERE {where}
"""


def fetch_all_for_analytics(
    *,
    status: str,
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _build_where(
        status=status,
        province=province,
        city=city,
        company="",
        product="",
        item="",
        category="",
        keyword="",
        date_from=date_from,
        date_to=date_to,
        mapped_only=True,
        prefix="f.",
    )
    table = MYSQL_TABLE
    sql = _ANALYTICS_SELECT.format(table=table, where=where)

    import pymysql

    records: list[dict[str, Any]] = []
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.SSDictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=600,
        write_timeout=600,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            while True:
                rows = cur.fetchmany(5000)
                if not rows:
                    break
                records.extend(row_to_analytics_record(row) for row in rows)
    finally:
        conn.close()
    return records


def count_unqualified_item_events(
    *,
    province: str = "全部",
    city: str = "全部",
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """不合格项次：与 analytics 饼图/总览一致的项目计数。"""
    from food_inspection.analytics import _unqualified_item_weight

    where, params = _build_where(
        status="unqualified",
        province=province,
        city=city,
        company="",
        product="",
        item="",
        category="",
        keyword="",
        date_from=date_from,
        date_to=date_to,
        mapped_only=True,
    )
    table = MYSQL_TABLE
    sql = _ANALYTICS_SELECT.format(table=table, where=where)

    import pymysql

    total = 0
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.SSDictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=600,
        write_timeout=600,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            while True:
                rows = cur.fetchmany(5000)
                if not rows:
                    break
                for row in rows:
                    total += _unqualified_item_weight(row_to_analytics_record(row))
    finally:
        conn.close()
    return total
