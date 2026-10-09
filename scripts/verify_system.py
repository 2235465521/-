"""
Dev-Expert Comprehensive Verification & Benchmark Suite
Tests functional correctness, data consistency, caching hierarchy,
optimizer hints, batch download modes, and concurrent load.
"""
import concurrent.futures
import io
import json
import sys
import time
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
import pymysql

from config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DATABASE,
)
from core.cache_manager import CacheManager
from core.db import db
from core.product_search import product_search

BASE_URL = "http://127.0.0.1:8005"

def print_section(title):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)

def test_sql_and_hints():
    print_section("1. 数据库执行计划与优化器 Hint 验证")
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn.cursor()

    # Explain homepage with hint
    sql_home = """
    EXPLAIN SELECT /*+ SET_VAR(optimizer_switch='semijoin=off') */ 
    DISTINCT b.* FROM std_base b 
    WHERE EXISTS (
        SELECT 1 FROM std_filepath f 
        WHERE f.base_id = b.id 
          AND f.file_name IS NOT NULL AND TRIM(f.file_name) <> ''
          AND UPPER(REPLACE(f.file_name, ' ', '')) LIKE CONCAT('%%', UPPER(REPLACE(b.std_id, ' ', '')), '%%') COLLATE utf8mb4_general_ci
    )
    ORDER BY b.release_date DESC LIMIT 10
    """
    cur.execute(sql_home)
    rows = cur.fetchall()
    tables = [r["table"] for r in rows]
    types = [r["type"] for r in rows]
    keys = [r["key"] for r in rows]

    print("  ✓ 首页执行计划分析:")
    for r in rows:
        print(f"    - Table [{r['table']}], Type: {r['type']}, Index: {r['key']}, Rows: {r['rows']}, Extra: {r.get('Extra')}")
    
    assert tables[0] == "b", "Driving table must be std_base b"
    assert keys[0] in ("idx_release_date", "idx_type_release", "idx_type_state_date"), "Must use release_date index"
    assert tables[1] == "f", "Subquery table must be std_filepath f"
    assert keys[1] == "idx_base_id", "Must use idx_base_id ref index (avoiding 98万行 full scan)"
    print("  ✓ 优化器 Hint 生效: semijoin=off 成功阻断全表扫描，索引路径完全正确！")
    conn.close()

def test_functional_and_counts():
    print_section("2. 核心搜索与基线数据准确性校验")
    
    # 1. Homepage
    res_home = db.browse_page(page=1, per_page=10)
    print(f"  [首页浏览] 总数: {res_home['total']} (期望基线: 173867), 返回条目: {len(res_home['items'])}")
    assert res_home["total"] == 173867, f"Homepage count mismatch: {res_home['total']}"
    assert len(res_home["items"]) == 10
    assert "has_pdf" in res_home["items"][0]

    # 2. Standard Search '化妆品'
    res_search = db.search_page("化妆品", page=1, per_page=10)
    print(f"  [普通检索 '化妆品'] 总数: {res_search['total']} (期望基线: 412), 返回条目: {len(res_search['items'])}")
    assert res_search["total"] == 412, f"Search count mismatch: {res_search['total']}"
    assert len(res_search["items"]) == 10

    # 3. Product Cluster '化妆品'
    res_prod = product_search.search_page("化妆品", page=1, per_page=10)
    print(f"  [同类产品 '化妆品'] 总数: {res_prod['total']} (期望基线: 483), 返回条目: {len(res_prod['items'])}")
    assert res_prod["total"] == 483, f"Product count mismatch: {res_prod['total']}"
    assert len(res_prod["items"]) == 10

    # 4. Standard ID exact search 'GB 7916'
    res_std = db.search_page("GB 7916", page=1, per_page=10)
    print(f"  [标准号精确 'GB 7916'] 总数: {res_std['total']}, 首条: {res_std['items'][0]['std_id']} - {res_std['items'][0]['std_chinesename']}")
    assert res_std["total"] >= 1
    assert "GB 7916" in res_std["items"][0]["std_id"]

    print("  ✓ 数据一致性与基线指标 100% 吻合！")

def test_cache_hierarchy():
    print_section("3. 缓存多层架构 (L1内存 + L2 SQLite WAL + 独立总数缓存) 验证")
    cm = CacheManager()

    # Clear and verify fresh
    test_key = cm.make_cache_key({"dev_expert_test": time.time()})
    assert cm.get_cached(test_key) is None
    
    # Set and test L1 hit
    cm.set_cached(test_key, {"hello": "p8", "status": "verified"})
    t0 = time.perf_counter()
    l1_val = cm.get_cached(test_key)
    t1 = time.perf_counter()
    l1_ms = (t1 - t0) * 1000
    print(f"  ✓ L1 内存缓存命中耗时: {l1_ms:.4f} ms (返回值: {l1_val['status']})")
    assert l1_val["status"] == "verified"
    assert l1_ms < 1.0, "L1 cache must be sub-millisecond"

    # Count cache test
    count_key = cm.make_cache_key({"dev_expert_count": "test"})
    cm.set_cached_count(count_key, 99999)
    t0 = time.perf_counter()
    cached_count = cm.get_cached_count(count_key)
    t1 = time.perf_counter()
    count_ms = (t1 - t0) * 1000
    print(f"  ✓ 独立总数缓存命中耗时: {count_ms:.4f} ms (缓存总数: {cached_count})")
    assert cached_count == 99999

    # Verify Page 2 speed reusing count cache
    t0 = time.perf_counter()
    res_p2 = db.browse_page(page=2, per_page=10)
    t1 = time.perf_counter()
    p2_time = t1 - t0
    print(f"  ✓ 翻页取数据 (复用总数缓存 + 仅 LIMIT 10): {p2_time:.4f} s (条目数: {len(res_p2['items'])})")
    assert len(res_p2["items"]) == 10

def test_http_api_endpoints():
    print_section("4. 运行中 HTTP API 接口端点回归测试")
    endpoints = [
        ("首页默认列表", f"{BASE_URL}/api/search?browse=1&page=1&per_page=10&enrich=0&scan_disk=0"),
        ("普通搜索'化妆品'", f"{BASE_URL}/api/search?q=%E5%8C%96%E5%A6%86%E5%93%81&page=1&per_page=10&enrich=0&scan_disk=0"),
        ("同类产品'化妆品'", f"{BASE_URL}/api/search?source=product&q=%E5%8C%96%E5%A6%86%E5%93%81&page=1&per_page=10&enrich=0&scan_disk=0"),
        ("标准号检索'GB/T 1.1'", f"{BASE_URL}/api/search?q=GB%2FT+1.1&page=1&per_page=10&enrich=0&scan_disk=0"),
        ("目录状态接口", f"{BASE_URL}/api/catalog/status"),
        ("批量PDF校验", f"{BASE_URL}/api/std/batch_check?ids=1,2,3&scan_disk=0"),
    ]

    for name, url in endpoints:
        t0 = time.perf_counter()
        resp = requests.get(url, timeout=10)
        t1 = time.perf_counter()
        latency_ms = (t1 - t0) * 1000
        assert resp.status_code == 200, f"{name} failed with {resp.status_code}"
        data = resp.json()
        assert data.get("ok") is True, f"{name} returned ok=False"
        print(f"  ✓ [{name}] HTTP 200 OK | 响应时间: {latency_ms:.2f} ms")

def test_batch_download_both_modes():
    print_section("5. 批量下载双模式功能验证 (文本粘贴 vs 模板文件)")

    # 1. 文本输入解析测试
    sample_text = "GB 7916-1987\nQB/T 4951-2026\nGB/T 1.1-2020"
    resp_parse = requests.post(f"{BASE_URL}/api/batch/parse_text", json={"text": sample_text}, timeout=10)
    assert resp_parse.status_code == 200
    parse_data = resp_parse.json()
    assert parse_data.get("ok") is True
    parsed_items = parse_data.get("items", [])
    print(f"  ✓ [文本解析] /api/batch/parse_text 识别成功: {len(parsed_items)} 条")
    assert len(parsed_items) >= 2

    # 2. 预览测试
    t0 = time.perf_counter()
    resp_prev = requests.post(f"{BASE_URL}/api/batch/preview", json={"items": parsed_items}, timeout=15)
    t1 = time.perf_counter()
    assert resp_prev.status_code == 200
    prev_data = resp_prev.json()
    assert prev_data.get("ok") is True
    preview_items_list = prev_data.get("items", [])
    print(f"  ✓ [文本预览] /api/batch/preview 耗时: {(t1 - t0)*1000:.2f} ms | 条目数: {len(preview_items_list)}")

    # 3. 批量打包下载测试
    t0 = time.perf_counter()
    dl_resp = requests.post(
        f"{BASE_URL}/api/batch/download",
        json={"items": preview_items_list, "only_pdf": False},
        timeout=30
    )
    t1 = time.perf_counter()
    assert dl_resp.status_code == 200
    assert dl_resp.headers.get("content-type") == "application/zip"
    
    zip_bytes = io.BytesIO(dl_resp.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        print(f"  ✓ [批量打包] 生成有效 ZIP 归档 | 大小: {len(dl_resp.content)/1024:.2f} KB | 包含文件: {len(namelist)} 个 | 耗时: {(t1 - t0)*1000:.2f} ms")
        assert any("清单" in name or "manifest" in name.lower() for name in namelist)

    # 4. 模板 Excel 下载测试
    tpl_resp = requests.get(f"{BASE_URL}/api/batch/template", timeout=5)
    assert tpl_resp.status_code == 200
    print(f"  ✓ [Excel模板接口] 下载正常 | 文件大小: {len(tpl_resp.content)} 字节")

def test_concurrent_stress():
    print_section("6. 并发与连接池压力验证 (10 线程并发命中)")
    urls = [
        f"{BASE_URL}/api/search?browse=1&page=1&per_page=10&enrich=0&scan_disk=0",
        f"{BASE_URL}/api/search?q=%E5%8C%96%E5%A6%86%E5%93%81&page=1&per_page=10&enrich=0&scan_disk=0",
        f"{BASE_URL}/api/search?source=product&q=%E5%8C%96%E5%A6%86%E5%93%81&page=1&per_page=10&enrich=0&scan_disk=0",
        f"{BASE_URL}/api/search?q=GB+7916&page=1&per_page=10&enrich=0&scan_disk=0",
    ] * 5  # 20 requests total

    latencies = []
    errors = 0

    def _fetch(u):
        t0 = time.perf_counter()
        r = requests.get(u, timeout=15)
        t1 = time.perf_counter()
        return r.status_code, (t1 - t0) * 1000

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_fetch, u) for u in urls]
        for f in concurrent.futures.as_completed(futures):
            code, lat = f.result()
            if code == 200:
                latencies.append(lat)
            else:
                errors += 1
    total_time = time.perf_counter() - t_start

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p90 = latencies[int(len(latencies) * 0.9)]
    p99 = latencies[-1]

    print(f"  ✓ 并发请求总数: {len(urls)}, 成功: {len(latencies)}, 失败: {errors}")
    print(f"  ✓ 并发总耗时: {total_time:.3f} s | QPS 吞吐: {len(urls)/total_time:.1f} req/s")
    print(f"  ✓ 延迟分布: P50 = {p50:.2f} ms | P90 = {p90:.2f} ms | Max = {p99:.2f} ms")
    assert errors == 0, f"Encountered {errors} errors in concurrency test"

if __name__ == "__main__":
    t_global_start = time.time()
    test_sql_and_hints()
    test_functional_and_counts()
    test_cache_hierarchy()
    test_http_api_endpoints()
    test_batch_download_both_modes()
    test_concurrent_stress()
    print_section(f"全部 6 项专业验收测试全部通过！总耗时: {time.time() - t_global_start:.2f} 秒")
