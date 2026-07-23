"""行政区划与单位名（用于高级筛选下拉）— 仅 MySQL。"""
from __future__ import annotations

import pymysql

from settings import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)

_AREA_CACHE: list[dict] | None = None


def _area_sort_key(code: str | None) -> tuple:
    """按国家标准行政区划代码排序（如 110000 北京 → 370000 山东）。"""
    s = str(code or "").strip()
    if s.isdigit():
        return (0, int(s))
    return (1, s)


def _best_area_code(current: str | None, candidate: str | None) -> str:
    cur = str(current or "").strip()
    new = str(candidate or "").strip()
    if not cur:
        return new
    if not new:
        return cur
    return new if _area_sort_key(new) < _area_sort_key(cur) else cur


def _mysql_conn():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
    )


def _load_area_rows() -> list[dict]:
    global _AREA_CACHE
    if _AREA_CACHE is not None:
        return _AREA_CACHE
    rows: list[dict] = []
    try:
        conn = _mysql_conn()
    except Exception:
        _AREA_CACHE = []
        return _AREA_CACHE
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT area_code, province_name, city_name, county_name, level
                FROM area_dict
                ORDER BY area_code
                """
            )
            rows = list(cur.fetchall() or [])
    except Exception:
        rows = []
    finally:
        conn.close()
    _AREA_CACHE = rows
    return rows


def is_ready() -> bool:
    return bool(_load_area_rows())


def list_provinces() -> list[str]:
    best: dict[str, str] = {}
    for row in _load_area_rows():
        p = (row.get("province_name") or "").strip()
        if not p:
            continue
        best[p] = _best_area_code(best.get(p), row.get("area_code"))
    return [name for name, _ in sorted(best.items(), key=lambda x: _area_sort_key(x[1]))]


def list_cities(province: str) -> list[str]:
    province = (province or "").strip()
    if not province:
        return []
    best: dict[str, str] = {}
    for row in _load_area_rows():
        if (row.get("province_name") or "").strip() != province:
            continue
        c = (row.get("city_name") or "").strip()
        if not c:
            continue
        best[c] = _best_area_code(best.get(c), row.get("area_code"))
    return [name for name, _ in sorted(best.items(), key=lambda x: _area_sort_key(x[1]))]


def list_counties(province: str, city: str) -> list[str]:
    province = (province or "").strip()
    city = (city or "").strip()
    if not province or not city:
        return []
    best: dict[str, str] = {}
    for row in _load_area_rows():
        if (row.get("province_name") or "").strip() != province:
            continue
        if (row.get("city_name") or "").strip() != city:
            continue
        c = (row.get("county_name") or "").strip()
        if not c:
            continue
        best[c] = _best_area_code(best.get(c), row.get("area_code"))
    return [name for name, _ in sorted(best.items(), key=lambda x: _area_sort_key(x[1]))]


def suggest_companies(query: str, limit: int = 40) -> list[str]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        conn = _mysql_conn()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT unit_name FROM unit_dict
                WHERE unit_name LIKE %s
                ORDER BY
                  CASE WHEN unit_name LIKE %s THEN 0 ELSE 1 END,
                  CHAR_LENGTH(unit_name),
                  unit_name
                LIMIT %s
                """,
                (f"%{q}%", f"{q}%", max(limit * 2, limit)),
            )
            rows = cur.fetchall() or []
        seen: set[str] = set()
        out: list[str] = []
        for row in rows:
            name = str(row.get("unit_name") or "").strip()
            if not name:
                continue
            key = name.rstrip("。，,;；.·")
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
    finally:
        conn.close()
