"""
从桌面 mydate 的 SQL 导出构建本地 SQLite 索引（仅需 std_base + std_filepath）。
首次运行约需数分钟，之后检索无需 MySQL 密码。
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import DATA_DIR, SQL_DUMP_DIR, SQLITE_PATH
from core.sql_parser import iter_insert_rows


def _status(msg: str) -> None:
    print(msg, flush=True)


def build() -> None:
    base_sql = SQL_DUMP_DIR / "mydate_std_base.sql"
    path_sql = SQL_DUMP_DIR / "mydate_std_filepath.sql"
    if not base_sql.is_file():
        raise FileNotFoundError(f"未找到 {base_sql}")
    if not path_sql.is_file():
        raise FileNotFoundError(f"未找到 {path_sql}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SQLITE_PATH.exists():
        SQLITE_PATH.unlink()

    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE std_base (
            id INTEGER PRIMARY KEY,
            std_id TEXT NOT NULL,
            std_type TEXT,
            std_chinesename TEXT,
            std_status TEXT,
            ex_state INTEGER,
            release_date TEXT,
            implement_date TEXT,
            std_id_norm TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_std_id ON std_base(std_id);
        CREATE INDEX idx_std_id_norm ON std_base(std_id_norm);

        CREATE TABLE std_filepath (
            id INTEGER PRIMARY KEY,
            base_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER
        );
        CREATE INDEX idx_filepath_base ON std_filepath(base_id);
        """
    )

    t0 = time.time()
    _status(f"导入 std_base ← {base_sql}")
    batch: list[tuple] = []
    count = 0
    with base_sql.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "INSERT INTO `std_base`" not in line:
                continue
            for row in iter_insert_rows(line, "std_base"):
                if len(row) < 12:
                    continue
                base_id = int(row[0])
                std_id = row[1] or ""
                std_id_norm = "".join(std_id.upper().split())
                batch.append(
                    (
                        base_id,
                        std_id,
                        row[2],
                        row[5],
                        row[10],
                        int(row[11]) if row[11] is not None else None,
                        row[7],
                        row[8],
                        std_id_norm,
                    )
                )
                if len(batch) >= 5000:
                    conn.executemany(
                        "INSERT INTO std_base VALUES (?,?,?,?,?,?,?,?,?)",
                        batch,
                    )
                    count += len(batch)
                    batch.clear()
                    if count % 100000 == 0:
                        _status(f"  std_base: {count:,} 行")
    if batch:
        conn.executemany("INSERT INTO std_base VALUES (?,?,?,?,?,?,?,?,?)", batch)
        count += len(batch)
    conn.commit()
    _status(f"std_base 完成: {count:,} 行 ({time.time() - t0:.1f}s)")

    t1 = time.time()
    _status(f"导入 std_filepath ← {path_sql}")
    batch = []
    fcount = 0
    with path_sql.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "INSERT INTO `std_filepath`" not in line:
                continue
            for row in iter_insert_rows(line, "std_filepath"):
                if len(row) < 5:
                    continue
                batch.append(
                    (
                        int(row[0]),
                        int(row[1]),
                        row[2] or "",
                        row[3] or "",
                        int(row[5]) if row[5] is not None else None,
                    )
                )
                if len(batch) >= 5000:
                    conn.executemany(
                        "INSERT INTO std_filepath VALUES (?,?,?,?,?)",
                        batch,
                    )
                    fcount += len(batch)
                    batch.clear()
                    if fcount % 100000 == 0:
                        _status(f"  std_filepath: {fcount:,} 行")
    if batch:
        conn.executemany("INSERT INTO std_filepath VALUES (?,?,?,?,?)", batch)
        fcount += len(batch)
    conn.commit()
    conn.close()
    _status(f"std_filepath 完成: {fcount:,} 行 ({time.time() - t1:.1f}s)")
    _status(f"索引已写入 {SQLITE_PATH}")


if __name__ == "__main__":
    try:
        build()
    except KeyboardInterrupt:
        sys.exit(1)
