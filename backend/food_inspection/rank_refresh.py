"""榜单预聚合 ETL：从 MySQL 实时计算 analytics 写入 stats_rank_cache（全国 + 各省）。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from food_inspection.rank_store import extract_products_payload, extract_units_payload

ProgressCallback = Callable[[str, int, int, str], None] | None

_MIN_VIOLATIONS = 2
_MIN_REPEAT_VIOLATIONS = 5
_DEFAULT_WORKERS = 6
_MAX_WORKERS = 6


def _read_provinces(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT province
            FROM dim_region
            WHERE province IS NOT NULL AND province <> ''
            ORDER BY province
            """
        )
        return [row["province"] for row in cur.fetchall()]


def _read_cached_provinces(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT province
            FROM stats_rank_cache
            WHERE city = ''
            """
        )
        return {row["province"] for row in cur.fetchall()}


def _clean_canonical_item_name(name: str) -> str:
    if not name:
        return ""
    text = str(name).strip()
    text = text.replace("（", "(").replace("）", ")").strip()
    
    if text in ("kg", "mg", "kg)", "mg)", "gkg", "gkg)", "计),mg", "mgkg", "汤碗", "餐碗", "瓷碗", "密胺碗", "餐饮具", "消毒餐具", "食品接触用纸包装及容器等制品", "食品接触用纸", "纸包装及容器", "食品接触用", "包装及容器") or text.lower() in ("kg", "mg", "gkg"):
        return ""
    if text.startswith("4-滴") or text.startswith("2,4-滴"):
        return "2,4-滴"
    if text in ("以Al计", "样品以Al计", "以Al", "Al计", "AI计", "以AI计") or "铝的残留" in text or text.startswith("铝") or "Al计" in text:
        return "铝的残留量"
    if text in ("以Pb计", "样品以Pb计", "Pb计") or text.startswith("铅"):
        return "铅"
    if text in ("以Cd计", "样品以Cd计", "Cd计", "镉(以)", "镉(以Cd计)", "镉(以)") or text.startswith("镉"):
        return "镉"
    if text.startswith("大肠"):
        return "大肠菌群"
    if "阴离子" in text or "洗涤剂" in text:
        return "阴离子合成洗涤剂"
    if text.startswith("酸价"):
        return "酸价"

    text = re.sub(r"\([^()]*以[^()]*计?\)", "", text).strip()
    text = re.sub(r"\(干样品[^()]*\)", "", text).strip()
    text = re.sub(r"\(以[^()]*\)", "", text).strip()
    text = text.replace("KOH", "").replace("(", "").replace(")", "").strip()

    if not text or text in ("其他", "未标注", "复检结果", "报告"):
        return ""

    return text


def _compute_analytics(province: str) -> dict[str, Any] | None:
    """直接从 agg_company_leaderboard 和 agg_product_leaderboard 快速构建榜单快照。"""
    import pymysql
    import re
    from collections import Counter
    from food_inspection.db import connection

    with connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            p_clause = "WHERE company_role = 'sampled_unit' AND list_type = 'RED' AND total_count > 5" + (" AND province = %s" if province != '全部' else "")
            p_params = [province] if province != '全部' else []

            # 1. 被抽检单位红榜 (top_failure_companies) 按不合格率
            cur.execute(f"""
                SELECT company_name as company, passed_count as qualified_count, 
                       failed_count as unqualified_count, total_count, unqualified_rate as failure_rate, province, city
                FROM agg_company_leaderboard
                {p_clause}
                ORDER BY unqualified_rate DESC, failed_count DESC, total_count DESC
                LIMIT 50;
            """, p_params)
            top_failure_companies = cur.fetchall()
            for c in top_failure_companies:
                c['failure_rate'] = float(c['failure_rate'])
                c['cities'] = [c['city']] if c['city'] else []
                c['address'] = f"{c.get('province','')}{c.get('city','')}"

            # 2. 被抽检单位绿榜 (perfect_companies)
            p_g_clause = "WHERE company_role = 'sampled_unit' AND list_type = 'GREEN' AND total_count > 5" + (" AND province = %s" if province != '全部' else "")
            cur.execute(f"""
                SELECT company_name as company, passed_count as qualified_count, total_count, 100.0 as pass_rate, province, city
                FROM agg_company_leaderboard
                {p_g_clause}
                ORDER BY total_count DESC, passed_count DESC
                LIMIT 100;
            """, p_params)
            perfect_companies = cur.fetchall()
            for c in perfect_companies:
                c['pass_rate'] = 100.0
                c['cities'] = [c['city']] if c['city'] else []
                c['address'] = f"{c.get('province','')}{c.get('city','')}"

            # 3. 生产单位红榜 (top_failure_manufacturers) 按生产地址归属!
            m_clause = "WHERE company_role = 'manufacturer' AND list_type = 'RED' AND total_count > 5" + (" AND province = %s" if province != '全部' else "")
            cur.execute(f"""
                SELECT company_name as company, passed_count as qualified_count, 
                       failed_count as unqualified_count, total_count, unqualified_rate as failure_rate, province, city
                FROM agg_company_leaderboard
                {m_clause}
                ORDER BY unqualified_rate DESC, failed_count DESC, total_count DESC
                LIMIT 50;
            """, p_params)
            top_failure_manufacturers = cur.fetchall()
            for m in top_failure_manufacturers:
                m['failure_rate'] = float(m['failure_rate'])
                m['cities'] = [m['city']] if m['city'] else []
                m['address'] = f"{m.get('province','')}{m.get('city','')}"

            # 4. 生产单位绿榜 (perfect_manufacturers)
            m_g_clause = "WHERE company_role = 'manufacturer' AND list_type = 'GREEN' AND total_count > 5" + (" AND province = %s" if province != '全部' else "")
            cur.execute(f"""
                SELECT company_name as company, passed_count as qualified_count, total_count, 100.0 as pass_rate, province, city
                FROM agg_company_leaderboard
                {m_g_clause}
                ORDER BY total_count DESC, passed_count DESC
                LIMIT 100;
            """, p_params)
            perfect_manufacturers = cur.fetchall()
            for m in perfect_manufacturers:
                m['pass_rate'] = 100.0
                m['cities'] = [m['city']] if m['city'] else []
                m['address'] = f"{m.get('province','')}{m.get('city','')}"

            # 5. 多次违规被抽检单位 (repeat_companies) - 不合格次数 > 5
            p_repeat_clause = "WHERE company_role = 'sampled_unit' AND failed_count > 5" + (" AND province = %s" if province != '全部' else "")
            cur.execute(f"""
                SELECT company_name as company, failed_count as count, passed_count as qualified_count,
                       total_count, unqualified_rate, province, city
                FROM agg_company_leaderboard
                {p_repeat_clause}
                ORDER BY failed_count DESC, unqualified_rate DESC
                LIMIT 100;
            """, p_params)
            repeat_companies = cur.fetchall()
            for rc in repeat_companies:
                rc['cities'] = [rc['city']] if rc['city'] else []
                rc['address'] = f"{rc.get('province','')}{rc.get('city','')}"
                rc['unqualified_rate'] = float(rc['unqualified_rate'])

            # 6. 城市不合格率 (cities) - 按不合格率从高到低排序
            city_where = "WHERE city IS NOT NULL AND city <> '' AND city <> '未知'" + (" AND province = %s" if province != '全部' else "")
            city_params = [province] if province != '全部' else []
            cur.execute(f"""
                SELECT city as name, 
                       SUM(qualified_count + unqualified_row_count) as total_count, 
                       SUM(unqualified_row_count) as unqualified_count,
                       ROUND(SUM(unqualified_row_count) / SUM(qualified_count + unqualified_row_count) * 100, 2) as ratio
                FROM stats_region
                {city_where}
                GROUP BY city
                HAVING total_count >= 10
                ORDER BY ratio DESC, unqualified_count DESC
                LIMIT 50;
            """, city_params)
            cities = cur.fetchall()
            for c in cities:
                c['ratio'] = float(c['ratio'] or 0)
                c['total_count'] = int(c['total_count'] or 0)
                c['unqualified_count'] = int(c['unqualified_count'] or 0)
                c['count'] = c['unqualified_count']

            # 7 & 8. 产品不合格率 (top_failure_products) 与 高频违规产品 (repeat_products)
            from food_inspection.analytics import canonical_tableware_product_name

            cur.execute("""
                SELECT food_standard_name as raw_product, passed_count as qualified_count, 
                       failed_count as unqualified_count, total_count
                FROM agg_product_leaderboard
                WHERE failed_count > 0;
            """)
            raw_product_rows = cur.fetchall()

            product_map = {}
            for r in raw_product_rows:
                raw_p = r['raw_product'] or ''
                p_name = canonical_tableware_product_name(raw_p)
                if not p_name:
                    continue
                if p_name not in product_map:
                    product_map[p_name] = {
                        'product': p_name,
                        'qualified_count': 0,
                        'unqualified_count': 0,
                        'total_count': 0,
                    }
                product_map[p_name]['qualified_count'] += int(r['qualified_count'] or 0)
                product_map[p_name]['unqualified_count'] += int(r['unqualified_count'] or 0)
                product_map[p_name]['total_count'] += int(r['total_count'] or 0)

            valid_product_list = []
            for p_name, item in product_map.items():
                tot = item['total_count']
                failed = item['unqualified_count']
                if tot >= 20 and failed > 0:
                    rate = round(failed / tot * 100, 2)
                    valid_product_list.append({
                        'product': p_name,
                        'qualified_count': item['qualified_count'],
                        'unqualified_count': failed,
                        'count': failed,
                        'total_count': tot,
                        'failure_rate': rate,
                        'unqualified_rate': rate,
                    })

            top_failure_products = sorted(
                valid_product_list,
                key=lambda x: (x['failure_rate'], x['unqualified_count'], x['total_count']),
                reverse=True
            )[:50]

            repeat_products = sorted(
                valid_product_list,
                key=lambda x: (x['count'], x['unqualified_rate'], x['total_count']),
                reverse=True
            )[:50]

            _breakdown_cache = {}
            def _fetch_item_breakdown(prod_name):
                if prod_name in _breakdown_cache:
                    return _breakdown_cache[prod_name]
                if prod_name in ('餐饮具', '复用餐饮具'):
                    cur.execute("""
                        SELECT u.item_name, COUNT(*) as cnt
                        FROM fact_unqualified_item u
                        JOIN fact_food_inspection f ON u.inspection_id = f.id
                        WHERE f.food_standard_name REGEXP '[碗筷碟盘盆杯勺]' OR f.minor_category REGEXP '[碗筷碟盘盆杯勺]' OR f.food_name REGEXP '[碗筷碟盘盆杯勺]' OR f.major_category LIKE '%%餐饮具%%' OR f.food_standard_name LIKE '%%餐饮具%%'
                        GROUP BY u.item_name
                        ORDER BY cnt DESC
                        LIMIT 12;
                    """)
                else:
                    cur.execute("""
                        SELECT u.item_name, COUNT(*) as cnt
                        FROM fact_unqualified_item u
                        JOIN fact_food_inspection f ON u.inspection_id = f.id
                        WHERE f.food_standard_name = %s OR f.minor_category = %s
                        GROUP BY u.item_name
                        ORDER BY cnt DESC
                        LIMIT 12;
                    """, (prod_name, prod_name))
                raw_items = cur.fetchall()
                merged_counter = Counter()
                for r in raw_items:
                    cleaned_name = _clean_canonical_item_name(r['item_name'])
                    if cleaned_name and cleaned_name not in ('未标注', '其他'):
                        merged_counter[cleaned_name] += int(r['cnt'])
                tot = sum(merged_counter.values())
                res = [
                    {'name': name, 'count': cnt, 'ratio': round(cnt / tot * 100, 2) if tot else 0.0}
                    for name, cnt in merged_counter.most_common(6)
                ]
                _breakdown_cache[prod_name] = res
                return res

            for p in top_failure_products:
                p['failure_rate'] = float(p['failure_rate'])
                p['item_breakdown'] = _fetch_item_breakdown(p['product'])

            for rp in repeat_products:
                rp['unqualified_rate'] = float(rp['unqualified_rate'])
                rp['item_breakdown'] = _fetch_item_breakdown(rp['product'])

            # 9. 不合格项目占比 (item_types) - 规范化与主干合并清洗
            item_where = "WHERE item_name IS NOT NULL AND TRIM(item_name) <> '' AND item_name <> '未标注'"
            item_params = []
            if province != '全部':
                item_where += " AND f.province = %s"
                item_params.append(province)
                cur.execute(f"""
                    SELECT u.item_name as name, COUNT(*) as count
                    FROM fact_unqualified_item u
                    JOIN fact_food_inspection f ON f.id = u.inspection_id
                    {item_where}
                    GROUP BY u.item_name;
                """, item_params)
            else:
                cur.execute(f"""
                    SELECT item_name as name, COUNT(*) as count
                    FROM fact_unqualified_item
                    {item_where}
                    GROUP BY item_name;
                """)
            raw_item_rows = cur.fetchall()
            item_counts = {}
            for r in raw_item_rows:
                c_name = _clean_canonical_item_name(r['name'])
                if not c_name:
                    continue
                item_counts[c_name] = item_counts.get(c_name, 0) + int(r['count'] or 0)

            sorted_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:50]
            item_total = sum(cnt for _, cnt in sorted_items)
            item_types = [{"name": name, "count": cnt, "ratio": round(cnt / item_total * 100, 2) if item_total else 0.0} for name, cnt in sorted_items]

            return {
                "province": province,
                "city": "全部",
                "total": sum(c['total_count'] for c in top_failure_companies) + sum(c['total_count'] for c in perfect_companies),
                "top_failure_companies": top_failure_companies,
                "perfect_companies": perfect_companies,
                "top_failure_manufacturers": top_failure_manufacturers,
                "perfect_manufacturers": perfect_manufacturers,
                "top_failure_products": top_failure_products,
                "repeat_companies": repeat_companies,
                "repeat_company_count": len(repeat_companies),
                "perfect_company_count": len(perfect_companies),
                "perfect_manufacturer_count": len(perfect_manufacturers),
                "repeat_products": repeat_products,
                "repeat_product_count": len(repeat_products),
                "cities": cities,
                "item_types": item_types,
                "item_types_total": item_total,
                "item_types_unique": len(item_types),
            }


def _write_scope(
    conn,
    province: str,
    analytics: dict[str, Any],
) -> None:
    units = extract_units_payload(analytics)
    products = extract_products_payload(analytics)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stats_rank_cache (
              province, city, units_json, products_json, refreshed_at
            ) VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
              units_json = VALUES(units_json),
              products_json = VALUES(products_json),
              refreshed_at = VALUES(refreshed_at)
            """,
            (
                province,
                "",
                json.dumps(units, ensure_ascii=False),
                json.dumps(products, ensure_ascii=False),
            ),
        )


def _refresh_one_scope(province: str) -> tuple[str, bool, float]:
    """计算并写入单省榜单，独立连接、立即 commit。"""
    from food_inspection.db import connection

    t0 = time.perf_counter()
    analytics = _compute_analytics(province)
    if not analytics or analytics.get("loading"):
        return province, False, round(time.perf_counter() - t0, 1)

    with connection() as conn:
        _write_scope(conn, province, analytics)
        conn.commit()

    return province, True, round(time.perf_counter() - t0, 1)


def refresh_rank_cache(
    conn,
    *,
    include_provinces: bool = True,
    only_missing: bool = False,
    max_workers: int | None = None,
    on_progress: ProgressCallback = None,
) -> dict[str, Any]:
    """并行计算全国 + 各省榜单（默认 2 路），每省算完即写入并 commit。"""
    from food_inspection.mysql_search import mysql_enabled

    if not mysql_enabled():
        return {
            "rank_rows": 0,
            "rank_elapsed_sec": 0,
            "rank_provinces": 0,
            "rank_skipped": 0,
            "rank_workers": 0,
        }

    workers = max_workers
    if workers is None:
        workers = int(os.environ.get("RANK_REFRESH_WORKERS", str(_DEFAULT_WORKERS)))
    workers = max(1, min(workers, _MAX_WORKERS))

    scopes: list[str] = ["全部"]
    if include_provinces:
        scopes.extend(_read_provinces(conn))

    if only_missing:
        cached = _read_cached_provinces(conn)
        scopes = [scope for scope in scopes if scope not in cached]

    total = len(scopes)
    if total == 0:
        return {
            "rank_rows": 0,
            "rank_elapsed_sec": 0,
            "rank_provinces": 0,
            "rank_skipped": 0,
            "rank_workers": workers,
        }

    t0 = time.perf_counter()
    rows_written = 0
    rows_skipped = 0
    progress_lock = threading.Lock()
    completed = 0

    def _report(province: str, ok: bool, elapsed_sec: float) -> None:
        nonlocal completed, rows_written, rows_skipped
        status = "完成" if ok else "跳过"
        with progress_lock:
            completed += 1
            index = completed
            if ok:
                rows_written += 1
            else:
                rows_skipped += 1
        if on_progress:
            on_progress(province, index, total, f"{status} {elapsed_sec}s")

    if workers == 1:
        for province in scopes:
            province, ok, elapsed_sec = _refresh_one_scope(province)
            _report(province, ok, elapsed_sec)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_refresh_one_scope, province): province for province in scopes}
            for future in as_completed(futures):
                province, ok, elapsed_sec = future.result()
                _report(province, ok, elapsed_sec)

    elapsed = round(time.perf_counter() - t0, 1)
    return {
        "rank_rows": rows_written,
        "rank_elapsed_sec": elapsed,
        "rank_provinces": max(total - (1 if "全部" in scopes else 0), 0),
        "rank_skipped": rows_skipped,
        "rank_workers": workers,
    }
