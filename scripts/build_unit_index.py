"""
从 SQL 导出构建 units.db（area_dict + unit_dict + std_unit_relation + 首家起草单位地址表）。
用于按省/市/区县/起草单位筛选标准（无需 MySQL 密码时）。
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import DATA_DIR, SQL_DUMP_DIR, UNITS_DB_PATH
from core.sql_parser import iter_insert_rows


def _status(msg: str) -> None:
    print(msg, flush=True)


def _import_table(
    conn: sqlite3.Connection,
    sql_path: Path,
    table: str,
    insert_sql: str,
    row_map,
    batch_size: int = 5000,
) -> int:
    if not sql_path.is_file():
        raise FileNotFoundError(f"未找到 {sql_path}")
    batch: list[tuple] = []
    count = 0
    with sql_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if f"INSERT INTO `{table}`" not in line:
                continue
            for row in iter_insert_rows(line, table):
                mapped = row_map(row)
                if mapped is None:
                    continue
                batch.append(mapped)
                if len(batch) >= batch_size:
                    conn.executemany(insert_sql, batch)
                    count += len(batch)
                    batch.clear()
                    if count % 100000 == 0:
                        _status(f"  {table}: {count:,} 行")
    if batch:
        conn.executemany(insert_sql, batch)
        count += len(batch)
    conn.commit()
    return count


_AREA_MATCH_SQL = """
LEFT JOIN area_dict a ON a.area_code = (
  SELECT ad.area_code FROM area_dict ad
  WHERE u.area_code IS NOT NULL AND u.area_code != ''
    AND (ad.area_code = u.area_code OR ad.area_code LIKE u.area_code || '%')
  ORDER BY length(ad.area_code) DESC
  LIMIT 1
)
"""


def _resolve_unit_sql_path() -> Path:
    preferred = sorted(
        SQL_DUMP_DIR.glob("mydate_unit_dict_回填后*.sql"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if preferred:
        return preferred[0]
    return SQL_DUMP_DIR / "mydate_unit_dict.sql"


def build() -> None:
    area_sql = SQL_DUMP_DIR / "mydate_area_dict.sql"
    unit_sql = _resolve_unit_sql_path()
    rel_sql = SQL_DUMP_DIR / "mydate_std_unit_relation.sql"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if UNITS_DB_PATH.exists():
        UNITS_DB_PATH.unlink()

    conn = sqlite3.connect(UNITS_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE area_dict (
            area_code TEXT PRIMARY KEY,
            province_name TEXT,
            city_name TEXT,
            county_name TEXT,
            level INTEGER
        );
        CREATE TABLE unit_dict (
            unit_id INTEGER PRIMARY KEY,
            unit_name TEXT NOT NULL,
            area_code TEXT
        );
        CREATE INDEX idx_unit_area ON unit_dict(area_code);
        CREATE INDEX idx_unit_name ON unit_dict(unit_name);

        CREATE TABLE std_unit_relation (
            id INTEGER PRIMARY KEY,
            base_id INTEGER NOT NULL,
            unit_id INTEGER NOT NULL,
            role_type INTEGER,
            rank_order INTEGER
        );
        CREATE INDEX idx_rel_base ON std_unit_relation(base_id);
        CREATE INDEX idx_rel_unit ON std_unit_relation(unit_id);

        CREATE TABLE std_unit_geo (
            base_id INTEGER NOT NULL,
            unit_id INTEGER NOT NULL,
            unit_name TEXT,
            province_name TEXT,
            city_name TEXT,
            county_name TEXT,
            area_code TEXT,
            PRIMARY KEY (base_id, unit_id)
        );
        CREATE INDEX idx_geo_base ON std_unit_geo(base_id);
        CREATE INDEX idx_geo_province ON std_unit_geo(province_name);
        CREATE INDEX idx_geo_city ON std_unit_geo(city_name);
        CREATE INDEX idx_geo_county ON std_unit_geo(county_name);
        CREATE INDEX idx_geo_unit_name ON std_unit_geo(unit_name);
        CREATE INDEX idx_rel_base_rank ON std_unit_relation(base_id, rank_order);
        CREATE INDEX idx_rel_rank_unit ON std_unit_relation(rank_order, unit_id);
        """
    )

    t0 = time.time()
    _status(f"导入 area_dict ← {area_sql}")
    n = _import_table(
        conn,
        area_sql,
        "area_dict",
        "INSERT OR REPLACE INTO area_dict VALUES (?,?,?,?,?)",
        lambda r: (r[0], r[1], r[2], r[3], int(r[4]) if r[4] is not None else None)
        if len(r) >= 5
        else None,
    )
    _status(f"area_dict 完成: {n:,} 行")

    _status(f"导入 unit_dict ← {unit_sql}")
    n = _import_table(
        conn,
        unit_sql,
        "unit_dict",
        "INSERT OR REPLACE INTO unit_dict VALUES (?,?,?)",
        lambda r: (int(r[0]), r[1] or "", r[2]) if len(r) >= 3 else None,
    )
    _status(f"unit_dict 完成: {n:,} 行")

    _status(f"导入 std_unit_relation ← {rel_sql}")
    n = _import_table(
        conn,
        rel_sql,
        "std_unit_relation",
        "INSERT OR REPLACE INTO std_unit_relation VALUES (?,?,?,?,?)",
        lambda r: (
            int(r[0]),
            int(r[1]),
            int(r[2]),
            int(r[3]) if r[3] is not None else 2,
            int(r[4]) if r[4] is not None else 0,
        )
        if len(r) >= 3
        else None,
    )
    _status(f"std_unit_relation 完成: {n:,} 行")

    _status("生成全部起草单位地址表 std_unit_geo（任一单位地址均可归类）…")
    conn.executescript(
        f"""
        INSERT INTO std_unit_geo (base_id, unit_id, unit_name, province_name, city_name, county_name, area_code)
        SELECT
          r.base_id,
          u.unit_id,
          u.unit_name,
          a.province_name,
          a.city_name,
          a.county_name,
          u.area_code
        FROM std_unit_relation r
        INNER JOIN unit_dict u ON u.unit_id = r.unit_id
        {_AREA_MATCH_SQL.strip()}
        WHERE a.province_name IS NOT NULL AND a.province_name != '';
        """
    )
    conn.commit()
    geo_count = conn.execute("SELECT COUNT(*) FROM std_unit_geo").fetchone()[0]
    std_count = conn.execute("SELECT COUNT(DISTINCT base_id) FROM std_unit_geo").fetchone()[0]
    fujian = conn.execute(
        "SELECT COUNT(DISTINCT base_id) FROM std_unit_geo WHERE province_name = ?",
        ("福建省",),
    ).fetchone()[0]
    conn.close()
    _status(
        f"std_unit_geo 完成: {geo_count:,} 条单位地址映射，"
        f"{std_count:,} 份标准（福建省 {fujian:,} 份）"
    )
    _status(f"索引已写入 {UNITS_DB_PATH} ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    try:
        build()
    except KeyboardInterrupt:
        sys.exit(1)
