#!/usr/bin/env python3
"""全量刷新预统计汇总表（stats_global / stats_region / dim_region）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path
import re

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts._bootstrap  # noqa: F401

_SCHEMA_PATH = BACKEND_DIR / "sql" / "stats_schema.sql"
_FILE_YEAR_RE = re.compile(r"(20\d{2})")


def _extract_year(file_name: str | None) -> str:
    text = str(file_name or "")
    match = _FILE_YEAR_RE.search(text)
    return match.group(1) if match else ""


def _ensure_schema(conn) -> None:
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    with conn.cursor() as cur:
        for statement in statements:
            if statement.upper().startswith("USE "):
                continue
            cur.execute(statement)
    conn.commit()


def _refresh_region(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE stats_region")
        cur.execute(
            """
            SELECT f.province, f.city, f.inspection_year, f.status
            FROM fact_food_inspection f
            WHERE f.province IS NOT NULL AND f.province <> ''
              AND TRIM(COALESCE(f.minor_category, '')) <> ''
            """
        )
        rows = cur.fetchall()
        bucket: dict[tuple[str, str, str], dict[str, int]] = {}
        for row in rows:
            province = str(row.get("province") or "").strip()
            city = str(row.get("city") or "").strip()
            year = str(row.get("inspection_year") or "").strip()
            status = str(row.get("status") or "").strip()
            key = (province, city, year)
            slot = bucket.setdefault(key, {"qualified": 0, "unqualified": 0})
            if status in ("合格", "1", "1.0") or row.get("status") == 1:
                slot["qualified"] += 1
            elif status in ("不合格", "0", "0.0") or row.get("status") == 0:
                slot["unqualified"] += 1

        for (province, city, year), counts in bucket.items():
            cur.execute(
                """
                INSERT INTO stats_region (province, city, year, qualified_count, unqualified_row_count)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (province, city, year, counts["qualified"], counts["unqualified"]),
            )
        count = len(bucket)
    conn.commit()
    return int(count or 0)


def _refresh_dim_region(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE dim_region")
        cur.execute(
            """
            INSERT INTO dim_region (province, city)
            SELECT DISTINCT province, COALESCE(city, '')
            FROM fact_food_inspection
            WHERE province IS NOT NULL AND province <> ''
              AND TRIM(COALESCE(minor_category, '')) <> ''
            """
        )
        cur.execute(
            """
            INSERT IGNORE INTO dim_region (province, city)
            SELECT DISTINCT province, ''
            FROM fact_food_inspection
            WHERE province IS NOT NULL AND province <> ''
              AND TRIM(COALESCE(minor_category, '')) <> ''
            """
        )
        count = cur.rowcount
    conn.commit()
    return int(count or 0)


def _count_unqualified_items(*, force_recount: bool = False) -> int:
    """不合格项次；默认读缓存，避免 ETL 每次扫 3 万行明细。"""
    if not force_recount:
        try:
            import json
            from pathlib import Path

            from config import ROOT_DIR

            cache_path = Path(ROOT_DIR) / "data" / "mysql_stats_cache.json"
            if cache_path.is_file():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                stats = payload.get("stats") or {}
                cached = int(stats.get("unqualified_count") or 0)
                if cached > 0:
                    return cached
        except Exception:
            pass

    try:
        from food_inspection.db import count_unqualified_item_events

        return int(count_unqualified_item_events())
    except Exception as exc:
        print(f"  警告：项次统计失败 ({exc})，使用批次数回退", flush=True)
    return 0


def _refresh_global(conn, *, force_recount: bool = False) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(qualified_count), 0) AS qualified_count,
              COALESCE(SUM(unqualified_row_count), 0) AS unqualified_row_count
            FROM stats_region
            """
        )
        row = cur.fetchone() or {}
        qualified_count = int(row.get("qualified_count") or 0)
        unqualified_row_count = int(row.get("unqualified_row_count") or 0)

        cur.execute(
            "SELECT COUNT(DISTINCT file_id) AS cnt FROM fact_food_inspection"
        )
        total_files = int((cur.fetchone() or {}).get("cnt") or 0)

    item_count = _count_unqualified_items(force_recount=force_recount)
    if item_count <= 0 and unqualified_row_count > 0:
        item_count = unqualified_row_count
        print(
            f"  项次回退为批次数: {item_count:,}",
            flush=True,
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stats_global (
              id, qualified_count, unqualified_row_count,
              unqualified_item_count, total_files, refreshed_at
            ) VALUES (1, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
              qualified_count = VALUES(qualified_count),
              unqualified_row_count = VALUES(unqualified_row_count),
              unqualified_item_count = VALUES(unqualified_item_count),
              total_files = VALUES(total_files),
              refreshed_at = VALUES(refreshed_at)
            """,
            (qualified_count, unqualified_row_count, item_count, total_files),
        )
    conn.commit()
    return {
        "qualified_count": qualified_count,
        "unqualified_row_count": unqualified_row_count,
        "unqualified_item_count": item_count,
        "total_files": total_files,
    }


def refresh_all(
    *,
    force_recount: bool = False,
    rank_only: bool = False,
    rank_only_missing: bool = False,
    rank_workers: int | None = None,
) -> dict[str, object]:
    from food_inspection.db import connection, mysql_enabled

    if not mysql_enabled():
        raise RuntimeError("USE_MYSQL 未启用")
    t0 = time.perf_counter()
    import pymysql

    conn = pymysql.connect(
        host=__import__("config").MYSQL_HOST,
        port=__import__("config").MYSQL_PORT,
        user=__import__("config").MYSQL_USER,
        password=__import__("config").MYSQL_PASSWORD,
        database=__import__("config").MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=600,
        write_timeout=600,
    )
    region_n = 0
    dim_n = 0
    global_stats: dict[str, int] = {}
    try:
        _ensure_schema(conn)
        if not rank_only:
            region_n = _refresh_region(conn)
            dim_n = _refresh_dim_region(conn)
            global_stats = _refresh_global(conn, force_recount=force_recount)
        from food_inspection.rank_refresh import refresh_rank_cache

        def _rank_progress(province: str, index: int, total: int, detail: str) -> None:
            print(
                f"  榜单预聚合 [{index}/{total}] {province} {detail}",
                flush=True,
            )

        rank_stats = refresh_rank_cache(
            conn,
            only_missing=rank_only_missing,
            max_workers=rank_workers,
            on_progress=_rank_progress,
        )
    finally:
        conn.close()

    elapsed = round(time.perf_counter() - t0, 1)
    return {
        "region_rows": region_n,
        "dim_rows": dim_n,
        "global": global_stats,
        "rank_rows": rank_stats.get("rank_rows", 0),
        "rank_elapsed_sec": rank_stats.get("rank_elapsed_sec", 0),
        "rank_provinces": rank_stats.get("rank_provinces", 0),
        "rank_skipped": rank_stats.get("rank_skipped", 0),
        "rank_workers": rank_stats.get("rank_workers", 0),
        "elapsed_sec": elapsed,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="刷新预统计汇总表")
    parser.add_argument(
        "--recount-items",
        action="store_true",
        help="重新扫描不合格项次（较慢，默认读缓存）",
    )
    parser.add_argument(
        "--rank-only",
        action="store_true",
        help="仅刷新 stats_rank_cache，跳过 stats_region/dim/global",
    )
    parser.add_argument(
        "--rank-only-missing",
        action="store_true",
        help="榜单仅刷新缓存中缺失的省份（断点续跑）",
    )
    parser.add_argument(
        "--rank-workers",
        type=int,
        default=6,
        help="榜单并行省数（默认 6，最大 6；内部 SQL 仍串行）",
    )
    args = parser.parse_args()

    from food_inspection.redis_cache import is_redis_available, redis_enabled
    from food_inspection.region_meta import invalidate_meta_cache

    print("开始刷新预统计汇总表…", flush=True)
    try:
        result = refresh_all(
            force_recount=args.recount_items,
            rank_only=args.rank_only,
            rank_only_missing=args.rank_only_missing,
            rank_workers=args.rank_workers,
        )
    except Exception as exc:
        print(f"刷新失败: {exc}", flush=True)
        return 1

    g = result.get("global") or {}
    summary = (
        f"刷新完成（{result['elapsed_sec']}s）："
        f"stats_rank_cache {result.get('rank_rows', 0)} 行（{result.get('rank_elapsed_sec', 0)}s，"
        f"{result.get('rank_workers', 2)} 并行，"
        f"覆盖 {result.get('rank_provinces', 0)} 省，跳过 {result.get('rank_skipped', 0)}）"
    )
    if g:
        summary += (
            f"，stats_region {result['region_rows']} 行，"
            f"dim_region {result['dim_rows']} 行，"
            f"合格 {g.get('qualified_count', 0):,}，"
            f"不合格项次 {g.get('unqualified_item_count', 0):,}，"
            f"文件 {g.get('total_files', 0):,}"
        )
    print(summary, flush=True)

    invalidate_meta_cache()

    try:
        from food_inspection.redis_cache import delete_prefix

        deleted = delete_prefix("rank:")
        if deleted:
            print(f"  已清除 {deleted} 条榜单 Redis 缓存", flush=True)
    except Exception:
        pass

    if redis_enabled() and is_redis_available():
        from food_inspection.mysql_stats import _write_stats_disk
        from food_inspection.stats_store import read_global_stats

        stats = read_global_stats()
        if stats:
            _write_stats_disk(stats)
            from food_inspection.redis_cache import set_json

            set_json(
                "mysql_stats",
                {
                    "cached_at": time.time(),
                    "schema_version": 3,
                    "stats": stats,
                },
                ttl_sec=86400,
            )
            print("  已同步 stats 到 Redis/磁盘缓存", flush=True)

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
