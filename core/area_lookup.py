"""行政区划与单位名（用于高级筛选下拉）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from paths import SQL_DUMP_DIR, UNITS_DB_PATH
from core.sql_parser import iter_insert_rows

_AREA_CACHE: list[dict] | None = None


def _load_area_rows() -> list[dict]:
    global _AREA_CACHE
    if _AREA_CACHE is not None:
        return _AREA_CACHE
    rows: list[dict] = []
    if UNITS_DB_PATH.is_file():
        conn = sqlite3.connect(UNITS_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                "SELECT area_code, province_name, city_name, county_name, level FROM area_dict"
            )
            rows = [dict(r) for r in cur.fetchall()]
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
    if not rows:
        sql_path = SQL_DUMP_DIR / "mydate_area_dict.sql"
        if sql_path.is_file():
            with sql_path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    for rec in iter_insert_rows(line, "area_dict"):
                        rows.append(
                            {
                                "area_code": rec[0],
                                "province_name": rec[1],
                                "city_name": rec[2],
                                "county_name": rec[3],
                                "level": rec[4],
                            }
                        )
    _AREA_CACHE = rows
    return rows


def is_ready() -> bool:
    return bool(_load_area_rows())


def list_provinces() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in _load_area_rows():
        p = (row.get("province_name") or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return sorted(out)


def list_cities(province: str) -> list[str]:
    province = (province or "").strip()
    if not province:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for row in _load_area_rows():
        if (row.get("province_name") or "").strip() != province:
            continue
        c = (row.get("city_name") or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return sorted(out)


def list_counties(province: str, city: str) -> list[str]:
    province = (province or "").strip()
    city = (city or "").strip()
    if not province or not city:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for row in _load_area_rows():
        if (row.get("province_name") or "").strip() != province:
            continue
        if (row.get("city_name") or "").strip() != city:
            continue
        c = (row.get("county_name") or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return sorted(out)


def suggest_companies(query: str, limit: int = 40) -> list[str]:
    q = (query or "").strip()
    if len(q) < 2 or not UNITS_DB_PATH.is_file():
        return []
    conn = sqlite3.connect(UNITS_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT unit_name FROM unit_dict
            WHERE unit_name LIKE ?
            ORDER BY
              CASE WHEN unit_name LIKE ? THEN 0 ELSE 1 END,
              length(unit_name),
              unit_name
            LIMIT ?
            """,
            (f"%{q}%", f"{q}%", max(limit * 2, limit)),
        ).fetchall()
        seen: set[str] = set()
        out: list[str] = []
        for row in rows:
            name = str(row[0]).strip()
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
    except sqlite3.Error:
        return []
    finally:
        conn.close()
