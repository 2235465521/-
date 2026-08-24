"""Flask HTTP API 路由层 (Web Routes Module)

利用 InspectionRepository Seam 消除所有底层存储分支与双轨逻辑：
- 路由层只负责 HTTP 请求参数解析、权限/有效性校验及 JSON 响应序列化。
- 所有数据检索、统计聚合与榜单计算均委托给统一的 InspectionRepository 接口。
"""

from __future__ import annotations

import os
import sys
from urllib.parse import quote

from flask import Flask, jsonify, request, send_file

from config import AUTO_SCAN_INTERVAL_SEC, CACHE_FILE, DATA_ROOT, ROOT_DIR
from food_inspection import store
from food_inspection.db import resolve_disk_path
from food_inspection.repository import get_current_repository


def register_routes(app: Flask) -> None:
    """向 Flask 注册核心业务与系统 API 路由"""

    @app.route("/api/status")
    def api_status():
        repo = get_current_repository()
        state = store.get_scan_state()
        pending = 0 if repo.is_mysql else store.refresh_pending_count()
        return jsonify(
            {
                **state,
                "has_cache": os.path.isfile(CACHE_FILE) or repo.is_ready(),
                "pending_new": pending,
                "pending_checking": False if repo.is_mysql else store.is_pending_count_computing(),
                "cache_loading": not repo.is_ready(),
                "auto_scan_interval_sec": AUTO_SCAN_INTERVAL_SEC,
            }
        )

    @app.route("/api/scan", methods=["POST"])
    def api_scan():
        state = store.get_scan_state()
        if state.get("running"):
            return jsonify({"ok": False, "message": "扫描正在进行中"}), 409

        full_rescan = request.args.get("full", "").lower() in ("1", "true", "yes")
        if not store.start_background_scan(full_rescan=full_rescan, trigger="manual"):
            return jsonify({"ok": False, "message": "扫描正在进行中"}), 409
        mode = "全量" if full_rescan else "增量"
        return jsonify({"ok": True, "message": f"已开始{mode}扫描（增量模式保留已解析数据）"})

    @app.route("/api/stats")
    def api_stats():
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        res = repo.get_stats(date_from=date_from, date_to=date_to)
        if res.get("loading") and not res.get("qualified_count"):
            return jsonify(res), 503
        return jsonify(res)

    @app.route("/api/provinces")
    def api_provinces():
        repo = get_current_repository()
        try:
            return jsonify(repo.get_provinces())
        except Exception as exc:
            return jsonify({"error": "省份列表检索失败", "message": str(exc)}), 503

    @app.route("/api/cities")
    def api_cities():
        province = request.args.get("province", "全部").strip() or "全部"
        repo = get_current_repository()
        try:
            return jsonify(repo.get_cities(province=province))
        except Exception as exc:
            return jsonify({"error": "城市列表检索失败", "message": str(exc)}), 503

    @app.route("/api/data")
    def api_data():
        status = request.args.get("type", "qualified")
        page = _safe_int(request.args.get("page"), 1, min_val=1)
        page_size = _safe_int(request.args.get("page_size"), 50, min_val=10, max_val=500)
        skip_total = request.args.get("skip_total", "").strip() in ("1", "true", "yes")
        province = request.args.get("province", "").strip() or "全部"
        city = request.args.get("city", "").strip() or "全部"
        date_from, date_to = _request_date_range()

        repo = get_current_repository()
        try:
            res = repo.search_records(
                status=status,
                province=province,
                city=city,
                county=request.args.get("county", "").strip(),
                company=request.args.get("company", "").strip(),
                product=request.args.get("product", "").strip(),
                category=request.args.get("category", "").strip(),
                item=request.args.get("item", "").strip(),
                reason=request.args.get("reason", "").strip(),
                q=request.args.get("q", "").strip(),
                entity_role=request.args.get("entity_role", "").strip(),
                date_from=date_from,
                date_to=date_to,
                page=page,
                page_size=page_size,
                skip_total=skip_total,
            )
            return jsonify(res)
        except Exception as exc:
            return jsonify({"error": "数据检索失败", "message": str(exc)}), 503

    @app.route("/api/scan_info")
    def api_scan_info():
        repo = get_current_repository()
        return jsonify(repo.get_scan_info())

    @app.route("/api/overview-chart")
    def api_overview_chart():
        province = request.args.get("province", "全部").strip()
        city = request.args.get("city", "全部").strip()
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        return jsonify(repo.get_overview_chart(province=province, city=city, date_from=date_from, date_to=date_to))

    @app.route("/api/overview-map")
    def api_overview_map():
        province = request.args.get("province", "全部").strip()
        city = request.args.get("city", "").strip()
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        res = repo.get_overview_map(province=province, city=city, date_from=date_from, date_to=date_to)
        if res.get("loading"):
            return jsonify(res), 503
        return jsonify(res)

    @app.route("/api/city-insights")
    def api_city_insights():
        province = request.args.get("province", "").strip()
        city = request.args.get("city", "全部").strip() or "全部"
        if not province or province == "全部":
            return jsonify({"error": "请指定省份"}), 400
        limit = _safe_int(request.args.get("limit"), 3, min_val=1, max_val=50)
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        res = repo.get_city_insights(province=province, city=city, date_from=date_from, date_to=date_to, limit=limit)
        if res.get("loading"):
            return jsonify(res), 503
        return jsonify(res)

    @app.route("/api/province-trend")
    def api_province_trend():
        province = request.args.get("province", "").strip()
        if not province or province in ("全部", "全国"):
            return jsonify({"error": "请指定省份"}), 400
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        try:
            return jsonify(repo.get_province_trend(province=province, date_from=date_from, date_to=date_to))
        except Exception as exc:
            return jsonify({"error": "趋势数据查询失败", "message": str(exc)}), 500

    @app.route("/api/analytics")
    def api_analytics():
        province = request.args.get("province", "全部").strip()
        city = request.args.get("city", "全部").strip()
        min_violations = _safe_int(request.args.get("min_violations"), 2, min_val=2)
        min_repeat_violations = _safe_int(request.args.get("min_repeat_violations"), 5, min_val=2)
        date_from, date_to = _request_date_range()
        force_refresh = request.args.get("refresh", "").strip() in ("1", "true", "yes")

        repo = get_current_repository()
        res = repo.get_analytics(
            province=province,
            city=city,
            min_violations=min_violations,
            min_repeat_violations=min_repeat_violations,
            date_from=date_from,
            date_to=date_to,
            force_refresh=force_refresh,
        )
        return jsonify(res)

    @app.route("/api/rank/units")
    def api_rank_units():
        province = request.args.get("province", "全部").strip()
        city = request.args.get("city", "全部").strip()
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        return jsonify(repo.get_unit_ranks(province=province, city=city, date_from=date_from, date_to=date_to))

    @app.route("/api/rank/products")
    def api_rank_products():
        province = request.args.get("province", "全部").strip()
        city = request.args.get("city", "全部").strip()
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        return jsonify(repo.get_product_ranks(province=province, city=city, date_from=date_from, date_to=date_to))

    @app.route("/api/company-stats")
    def api_company_stats():
        keyword = request.args.get("q", "").strip()
        province = request.args.get("province", "全部").strip()
        city = request.args.get("city", "全部").strip()
        date_from, date_to = _request_date_range()
        repo = get_current_repository()
        return jsonify(repo.get_company_stats(keyword=keyword, province=province, city=city, date_from=date_from, date_to=date_to))

    @app.route("/api/geo/<adcode>")
    def api_geo(adcode: str):
        import json as json_lib
        import urllib.error
        import urllib.request

        code = "".join(ch for ch in adcode if ch.isdigit())
        if not code:
            return jsonify({"error": "invalid adcode"}), 400
        geo_dir = os.path.join(ROOT_DIR, "geo_data")
        geo_path = os.path.join(geo_dir, f"{code}_full.json")
        if os.path.isfile(geo_path):
            return send_file(geo_path, mimetype="application/json")
        url = f"https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = json_lib.load(resp)
        except (urllib.error.URLError, TimeoutError, json_lib.JSONDecodeError, OSError) as exc:
            return jsonify({"error": f"地图数据加载失败: {code}", "detail": str(exc)}), 502
        if not payload.get("features"):
            return jsonify({"error": f"地图数据无效: {code}"}), 502
        os.makedirs(geo_dir, exist_ok=True)
        with open(geo_path, "w", encoding="utf-8") as handle:
            json_lib.dump(payload, handle, ensure_ascii=False)
        return jsonify(payload)

    @app.route("/api/download-file", methods=["GET"])
    def api_download_file():
        filepath = request.args.get("path", "")
        validated = _validate_source_path(filepath)
        if not validated:
            return jsonify({"ok": False, "message": "文件路径无效或不存在"}), 404
        return send_file(
            validated,
            as_attachment=True,
            download_name=os.path.basename(validated),
        )

    @app.route("/api/open-file", methods=["POST"])
    def api_open_file():
        payload = request.get_json(silent=True) or {}
        filepath = payload.get("path") or request.args.get("path", "")
        validated = _validate_source_path(filepath)
        if not validated:
            return jsonify({"ok": False, "message": "文件路径无效或不存在"}), 404

        if sys.platform == "win32" and hasattr(os, "startfile"):
            try:
                os.startfile(validated)
            except OSError as exc:
                return jsonify({"ok": False, "message": f"无法打开文件: {exc}"}), 500
            return jsonify({"ok": True, "mode": "local", "path": validated})

        return jsonify(
            {
                "ok": True,
                "mode": "download",
                "url": f"/api/download-file?path={quote(filepath, safe='')}",
                "path": validated,
            }
        )

    @app.before_request
    def _ensure_latest_cache():
        repo = get_current_repository()
        if repo.is_mysql:
            return
        if request.path in (
            "/api/overview-chart",
            "/api/overview-map",
            "/api/city-insights",
            "/api/analytics",
            "/api/rank/units",
            "/api/rank/products",
            "/api/data",
            "/api/health",
            "/api/stats",
            "/api/status",
            "/api/provinces",
            "/api/cities",
        ):
            return
        if not repo.is_ready():
            return
        state = store.get_scan_state()
        if request.path.startswith("/api/") and not state.get("running"):
            store.reload_data_if_cache_updated()


def _request_date_range() -> tuple[str | None, str | None]:
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    return date_from, date_to


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    try:
        num = int(str(val).strip())
    except (TypeError, ValueError):
        num = default
    if min_val is not None:
        num = max(num, min_val)
    if max_val is not None:
        num = min(num, max_val)
    return num


def _validate_source_path(filepath: str) -> str | None:
    if not filepath:
        return None
    normalized = os.path.normpath(filepath)
    root = os.path.normpath(DATA_ROOT)
    if normalized.startswith(root) and os.path.isfile(normalized):
        return normalized
    resolved = resolve_disk_path(filepath)
    if resolved and os.path.isfile(resolved):
        return resolved
    return None
