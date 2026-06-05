"""磁盘文件目录 FTS 索引（团标 / 制度等无数据库表场景）。"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


def fts_escape_token(token: str) -> str:
    return token.replace('"', '""')


def build_fts_query(q: str) -> str:
    tokens = re.findall(r"\S+", (q or "").strip())
    if not tokens:
        return ""
    return " OR ".join(f'"{fts_escape_token(t)}"*' for t in tokens[:8])


@dataclass
class CatalogEntry:
    id: int
    category: str
    title: str
    filename: str
    rel_path: str
    file_ext: str
    file_size: int | None


class DiskCatalog:
    def __init__(
        self,
        *,
        name: str,
        root_dir: Path,
        db_path: Path,
        table: str,
        extensions: frozenset[str],
        type_label: str,
    ) -> None:
        self.name = name
        self.root_dir = root_dir
        self.db_path = db_path
        self.table = table
        self.fts_table = f"{table}_fts"
        self.extensions = extensions
        self.type_label = type_label

    def dir_exists(self) -> bool:
        return self.root_dir.is_dir()

    def is_ready(self) -> bool:
        if not self.db_path.is_file():
            return False
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0]
                return n > 0
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def indexed_count(self) -> int:
        if not self.db_path.is_file():
            return 0
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                return int(conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0])
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    def describe(self) -> str:
        if not self.dir_exists():
            return f"{self.name}（目录不存在）"
        if not self.is_ready():
            return f"{self.name}（未建索引）"
        return f"{self.name}（{self.indexed_count():,} 份）"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS catalog_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS {self.table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                file_ext TEXT NOT NULL,
                file_size INTEGER,
                mtime REAL NOT NULL,
                rel_path TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_{self.table}_cat ON {self.table}(category);
            CREATE VIRTUAL TABLE IF NOT EXISTS {self.fts_table} USING fts5(
                category, title, filename,
                content='{self.table}', content_rowid='id',
                tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS {self.table}_ai AFTER INSERT ON {self.table} BEGIN
              INSERT INTO {self.fts_table}(rowid, category, title, filename)
              VALUES (new.id, new.category, new.title, new.filename);
            END;
            CREATE TRIGGER IF NOT EXISTS {self.table}_ad AFTER DELETE ON {self.table} BEGIN
              INSERT INTO {self.fts_table}({self.fts_table}, rowid, category, title, filename)
              VALUES ('delete', old.id, old.category, old.title, old.filename);
            END;
            CREATE TRIGGER IF NOT EXISTS {self.table}_au AFTER UPDATE ON {self.table} BEGIN
              INSERT INTO {self.fts_table}({self.fts_table}, rowid, category, title, filename)
              VALUES ('delete', old.id, old.category, old.title, old.filename);
              INSERT INTO {self.fts_table}(rowid, category, title, filename)
              VALUES (new.id, new.category, new.title, new.filename);
            END;
            """
        )

    def build_index(
        self,
        *,
        parse_row,
        progress=None,
    ) -> int:
        if not self.root_dir.is_dir():
            raise FileNotFoundError(f"目录不存在: {self.root_dir}")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema(conn)

        insert_sql = f"""
            INSERT INTO {self.table}
            (filename, category, title, file_ext, file_size, mtime, rel_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        batch: list[tuple] = []
        count = 0
        t0 = time.time()

        for path in self.root_dir.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in self.extensions:
                continue
            row = parse_row(path, self.root_dir)
            if not row:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            batch.append(
                (
                    row["filename"],
                    row["category"],
                    row["title"],
                    ext,
                    st.st_size,
                    st.st_mtime,
                    row["rel_path"],
                )
            )
            if len(batch) >= 2000:
                conn.executemany(insert_sql, batch)
                conn.commit()
                count += len(batch)
                batch.clear()
                if progress and count % 10000 == 0:
                    progress(count)

        if batch:
            conn.executemany(insert_sql, batch)
            conn.commit()
            count += len(batch)

        conn.execute(
            "INSERT OR REPLACE INTO catalog_meta VALUES (?, ?)",
            ("built_at", str(time.time())),
        )
        conn.execute(
            "INSERT OR REPLACE INTO catalog_meta VALUES (?, ?)",
            ("root_dir", str(self.root_dir)),
        )
        conn.commit()
        conn.close()
        if progress:
            progress(count, done=True, elapsed=time.time() - t0)
        return count

    def _row_to_item(self, row: sqlite3.Row) -> dict:
        ext = (row["file_ext"] or "").lower()
        label = "PDF" if ext == ".pdf" else "DOC" if ext in (".doc", ".docx") else ext.upper().lstrip(".") or "文件"
        return {
            "id": row["id"],
            "std_id": row["category"] or "—",
            "std_chinesename": row["title"] or row["filename"],
            "std_type": self.name,
            "std_status": label,
            "ex_state_label": label,
            "has_pdf": ext == ".pdf",
            "has_file": True,
            "files": [
                {
                    "id": row["id"],
                    "file_name": row["filename"],
                    "file_path": row["rel_path"],
                    "file_size": row["file_size"],
                    "file_ext": ext,
                    "exists": True,
                    "source": "catalog",
                }
            ],
        }

    def _search_where(self, q: str) -> tuple[str, list]:
        q = (q or "").strip()
        if not q:
            return "1=1", []
        fts_q = build_fts_query(q)
        if fts_q:
            return (
                f"id IN (SELECT rowid FROM {self.fts_table} WHERE {self.fts_table} MATCH ?)",
                [fts_q],
            )
        like = f"%{q}%"
        return (
            "(category LIKE ? OR title LIKE ? OR filename LIKE ?)",
            [like, like, like],
        )

    def search_page(self, q: str, *, page: int = 1, per_page: int = 10) -> dict:
        page = max(1, page)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        if not self.is_ready():
            return {
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
                "items": [],
                "search_mode": self.table,
                "catalog_ready": False,
            }

        where_sql, args = self._search_where(q)
        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {self.table} WHERE {where_sql}",
                    args,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                SELECT * FROM {self.table}
                WHERE {where_sql}
                ORDER BY category, title
                LIMIT ? OFFSET ?
                """,
                (*args, per_page, offset),
            ).fetchall()

        total_pages = (total + per_page - 1) // per_page if total else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": [self._row_to_item(r) for r in rows],
            "search_mode": self.table,
            "catalog_ready": True,
        }

    def get_by_id(self, file_id: int) -> CatalogEntry | None:
        if not self.is_ready():
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.table} WHERE id = ?",
                (file_id,),
            ).fetchone()
        if not row:
            return None
        return CatalogEntry(
            id=row["id"],
            category=row["category"],
            title=row["title"],
            filename=row["filename"],
            rel_path=row["rel_path"],
            file_ext=row["file_ext"],
            file_size=row["file_size"],
        )

    def resolve_path(self, file_id: int) -> Path | None:
        entry = self.get_by_id(file_id)
        if not entry:
            return None
        path = (self.root_dir / entry.rel_path).resolve()
        try:
            path.relative_to(self.root_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None
