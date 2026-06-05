"""起草单位 → 通讯地址所在省市（unit_dict + area_dict）。"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pymysql

from config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    SQL_DUMP_DIR,
    UNITS_DB_PATH,
)
from suggest import extract_phrases
from tuangbiao_catalog import _fts_escape

_AREA_CACHE: dict[str, dict] | None = None


@dataclass
class UnitAddress:
    unit_id: int
    unit_name: str
    area_code: str | None
    province: str | None
    city: str | None
    county: str | None
    address_text: str

    def to_dict(self) -> dict:
        return {
            "id": self.unit_id,
            "unit_name": self.unit_name,
            "area_code": self.area_code,
            "province": self.province,
            "city": self.city,
            "county": self.county,
            "address_text": self.address_text,
        }


def _format_address(
    province: str | None, city: str | None, county: str | None
) -> str:
    parts: list[str] = []
    if province:
        parts.append(province)
    if city and city not in parts and city != province:
        parts.append(city)
    if county and county not in parts:
        parts.append(county)
    return "".join(parts) if parts else "（库内暂无行政区划）"


def _row_area(row: dict) -> tuple[str | None, str | None, str | None]:
    return row.get("province_name"), row.get("city_name"), row.get("county_name")


class UnitLookup:
    def __init__(self) -> None:
        self._mysql_ok: bool | None = None

    def _mysql_can_connect(self) -> bool:
        if not MYSQL_PASSWORD:
            return False
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                charset="utf8mb4",
                connect_timeout=3,
            )
            conn.close()
            return True
        except Exception:
            return False

    def use_mysql(self) -> bool:
        if self._mysql_ok is not None:
            return self._mysql_ok
        if not self._mysql_can_connect():
            self._mysql_ok = False
            return False
        try:
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM unit_dict LIMIT 1")
                self._mysql_ok = True
        except Exception:
            self._mysql_ok = False
        return self._mysql_ok

    def _mysql(self):
        return pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(UNITS_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def indexed_count(self) -> int:
        if self.use_mysql():
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS c FROM unit_dict")
                return int(cur.fetchone()["c"])
        if not UNITS_DB_PATH.is_file():
            return 0
        with self._sqlite() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM unit_dict").fetchone()[0])

    def is_ready(self) -> bool:
        return self.indexed_count() > 0

    def describe(self) -> str:
        n = self.indexed_count()
        if n > 0:
            src = "MySQL" if self.use_mysql() else "本地索引"
            return f"起草单位库 ({n:,} 条，{src})"
        return "起草单位库未就绪（运行 python build_unit_index.py 或配置 MySQL）"

    def _load_area_cache(self) -> dict[str, dict]:
        global _AREA_CACHE
        if _AREA_CACHE is not None:
            return _AREA_CACHE
        rows: list[dict] = []
        if self.use_mysql():
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT area_code, province_name, city_name, county_name, level FROM area_dict"
                )
                rows = list(cur.fetchall())
        elif UNITS_DB_PATH.is_file():
            with self._sqlite() as conn:
                cur = conn.execute(
                    "SELECT area_code, province_name, city_name, county_name, level FROM area_dict"
                )
                rows = [dict(r) for r in cur.fetchall()]
        _AREA_CACHE = {str(r["area_code"]): r for r in rows}
        return _AREA_CACHE

    def resolve_area(self, area_code: str | None) -> tuple[str | None, str | None, str | None]:
        if not area_code:
            return None, None, None
        cache = self._load_area_cache()
        code = str(area_code).strip()
        if not code:
            return None, None, None

        if code in cache:
            return _row_area(cache[code])

        # 前缀匹配：3708 → 370800，31 → 31
        best: dict | None = None
        best_len = -1
        for ac, row in cache.items():
            if code.startswith(ac) or ac.startswith(code):
                ln = len(ac)
                if ln > best_len:
                    best_len = ln
                    best = row
        if best:
            return _row_area(best)

        # 补零到 6 位再试
        if len(code) < 6:
            padded = code.ljust(6, "0")
            if padded in cache:
                return _row_area(cache[padded])
        return None, None, None

    def _to_unit_address(self, row: dict) -> UnitAddress:
        province, city, county = self.resolve_area(row.get("area_code"))
        return UnitAddress(
            unit_id=int(row["unit_id"]),
            unit_name=row["unit_name"] or "",
            area_code=row.get("area_code"),
            province=province,
            city=city,
            county=county,
            address_text=_format_address(province, city, county),
        )

    def get_by_id(self, unit_id: int) -> UnitAddress | None:
        if self.use_mysql():
            with self._mysql() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT unit_id, unit_name, area_code FROM unit_dict WHERE unit_id = %s",
                    (unit_id,),
                )
                row = cur.fetchone()
                return self._to_unit_address(row) if row else None
        if not UNITS_DB_PATH.is_file():
            return None
        with self._sqlite() as conn:
            row = conn.execute(
                "SELECT unit_id, unit_name, area_code FROM unit_dict WHERE unit_id = ?",
                (unit_id,),
            ).fetchone()
            return self._to_unit_address(dict(row)) if row else None

    def _search_mysql(self, q: str, limit: int, offset: int) -> tuple[int, list[UnitAddress]]:
        like = f"%{q}%"
        with self._mysql() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS c FROM unit_dict WHERE unit_name LIKE %s",
                (like,),
            )
            total = int(cur.fetchone()["c"])
            cur.execute(
                """
                SELECT unit_id, unit_name, area_code FROM unit_dict
                WHERE unit_name LIKE %s
                ORDER BY
                  CASE WHEN unit_name = %s THEN 0
                       WHEN unit_name LIKE %s THEN 1
                       ELSE 2 END,
                  length(unit_name),
                  unit_name
                LIMIT %s OFFSET %s
                """,
                (like, q, f"{q}%", limit, offset),
            )
            items = [self._to_unit_address(r) for r in cur.fetchall()]
        return total, items

    def _search_sqlite(self, q: str, limit: int, offset: int) -> tuple[int, list[UnitAddress]]:
        fts_q = _fts_escape(q)
        like = f"%{q}%"
        with self._sqlite() as conn:
            if fts_q:
                try:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM unit_fts WHERE unit_fts MATCH ?",
                        (fts_q,),
                    ).fetchone()[0]
                    rows = conn.execute(
                        """
                        SELECT u.unit_id, u.unit_name, u.area_code
                        FROM unit_fts fts
                        JOIN unit_dict u ON u.unit_id = fts.rowid
                        WHERE unit_fts MATCH ?
                        ORDER BY rank, u.unit_name
                        LIMIT ? OFFSET ?
                        """,
                        (fts_q, limit, offset),
                    ).fetchall()
                    if rows:
                        return int(total), [
                            self._to_unit_address(dict(r)) for r in rows
                        ]
                except sqlite3.Error:
                    pass
            total = conn.execute(
                "SELECT COUNT(*) FROM unit_dict WHERE unit_name LIKE ?",
                (like,),
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT unit_id, unit_name, area_code FROM unit_dict
                WHERE unit_name LIKE ?
                ORDER BY unit_name
                LIMIT ? OFFSET ?
                """,
                (like, limit, offset),
            ).fetchall()
            items = [self._to_unit_address(dict(r)) for r in rows]
        return int(total), items

    def search_page(
        self, query: str, page: int = 1, per_page: int = 10
    ) -> dict:
        q = query.strip()
        if not q:
            return {
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
                "items": [],
                "source": "unit",
            }
        if not self.is_ready():
            return {
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
                "items": [],
                "error": "起草单位库未就绪，请运行 python build_unit_index.py 或配置 MySQL",
                "source": "unit",
            }
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        if self.use_mysql():
            total, items = self._search_mysql(q, per_page, offset)
        else:
            total, items = self._search_sqlite(q, per_page, offset)
        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": [x.to_dict() for x in items],
            "source": "unit",
        }

    def suggest(self, query: str, limit: int = 10) -> dict:
        q = query.strip()
        if not q or not self.is_ready():
            return {"phrases": [], "items": []}
        data = self.search_page(q, page=1, per_page=min(80, limit * 8))
        items = []
        names = []
        for row in data.get("items", []):
            names.append(row.get("unit_name") or "")
            if len(items) < limit:
                items.append(
                    {
                        "std_id": row.get("unit_name"),
                        "title": row.get("address_text") or "",
                        "search_text": q,
                        "unit_id": row.get("id"),
                    }
                )
        phrases = extract_phrases(names, q, max_phrases=8) if names else []
        if not phrases and q:
            phrases = [q]
        return {"phrases": phrases, "items": items}

    def rebuild_sqlite_index(
        self, progress: callable[[str], None] | None = None
    ) -> int:
        def log(msg: str) -> None:
            if progress:
                progress(msg)

        unit_sql = SQL_DUMP_DIR / "mydate_unit_dict.sql"
        area_sql = SQL_DUMP_DIR / "mydate_area_dict.sql"
        if not unit_sql.is_file():
            raise FileNotFoundError(f"未找到 {unit_sql}")
        if not area_sql.is_file():
            raise FileNotFoundError(f"未找到 {area_sql}")

        from sql_parser import iter_insert_rows

        if UNITS_DB_PATH.is_file():
            UNITS_DB_PATH.unlink()
        UNITS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(UNITS_DB_PATH)
        conn.executescript(
            """
            CREATE TABLE unit_dict (
                unit_id INTEGER PRIMARY KEY,
                unit_name TEXT NOT NULL UNIQUE,
                area_code TEXT
            );
            CREATE TABLE area_dict (
                area_code TEXT PRIMARY KEY,
                province_name TEXT,
                city_name TEXT,
                county_name TEXT,
                level INTEGER
            );
            CREATE VIRTUAL TABLE unit_fts USING fts5(
                unit_name,
                tokenize='unicode61'
            );
            """
        )

        log("导入 area_dict …")
        area_batch: list[tuple] = []
        with area_sql.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "INSERT INTO `area_dict`" not in line:
                    continue
                for row in iter_insert_rows(line, "area_dict"):
                    if len(row) < 5:
                        continue
                    area_batch.append(
                        (
                            row[0],
                            row[1],
                            row[2],
                            row[3],
                            int(row[4]) if row[4] is not None else 0,
                        )
                    )
        conn.executemany(
            "INSERT INTO area_dict VALUES (?,?,?,?,?)",
            area_batch,
        )
        log(f"  area_dict: {len(area_batch):,} 条")

        log("导入 unit_dict …")
        unit_batch: list[tuple] = []
        count = 0
        with unit_sql.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "INSERT INTO `unit_dict`" not in line:
                    continue
                for row in iter_insert_rows(line, "unit_dict"):
                    if len(row) < 2:
                        continue
                    unit_batch.append(
                        (int(row[0]), row[1] or "", row[2] if len(row) > 2 else None)
                    )
                    if len(unit_batch) >= 5000:
                        conn.executemany(
                            "INSERT INTO unit_dict VALUES (?,?,?)",
                            unit_batch,
                        )
                        count += len(unit_batch)
                        unit_batch.clear()
                        if count % 50000 == 0:
                            log(f"  unit_dict: {count:,} 行")
        if unit_batch:
            conn.executemany("INSERT INTO unit_dict VALUES (?,?,?)", unit_batch)
            count += len(unit_batch)

        log("构建全文索引…")
        conn.execute(
            "INSERT INTO unit_fts(rowid, unit_name) SELECT unit_id, unit_name FROM unit_dict"
        )
        conn.commit()
        conn.close()
        global _AREA_CACHE
        _AREA_CACHE = None
        self._mysql_ok = None
        log(f"完成 unit_dict: {count:,} 条")
        return count


unit_lookup = UnitLookup()
