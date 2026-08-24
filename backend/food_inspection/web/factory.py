"""Flask 应用工厂：先监听 8080，后台再加载 pandas 等重模块。"""

from __future__ import annotations

import os
import threading
import traceback

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

from config import AUTO_SCAN_INTERVAL_SEC, CACHE_FILE, CORS_ORIGINS, SERVE_STATIC, STATIC_DIR

_module_ready = False
_module_error: str | None = None
_module_lock = threading.Lock()


def is_module_ready() -> bool:
    return _module_ready


def create_app() -> Flask:
    global _module_ready, _module_error
    _module_ready = False
    _module_error = None

    app = Flask(__name__)
    if CORS_ORIGINS:
        CORS(app, resources={r"/api/*": {"origins": CORS_ORIGINS}}, supports_credentials=True)

    @app.route("/api/health")
    def api_health():
        payload: dict = {
            "ok": _module_error is None and _module_ready,
            "service": "food-inspection-api",
            "loading": not _module_ready,
            "module_error": _module_error,
            "cache_loading": not _module_ready,
        }
        if _module_ready and _module_error is None:
            from config import USE_MYSQL
            from food_inspection.redis_cache import is_redis_available, redis_enabled

            payload["data_source"] = "mysql" if USE_MYSQL else "cache"
            payload["redis_enabled"] = redis_enabled()
            payload["redis_available"] = is_redis_available() if redis_enabled() else False
            try:
                from food_inspection.rank_store import rank_tables_ready
                from food_inspection.stats_store import stats_tables_ready

                payload["stats_tables_ready"] = stats_tables_ready()
                payload["rank_tables_ready"] = rank_tables_ready()
            except Exception:
                payload["stats_tables_ready"] = False
                payload["rank_tables_ready"] = False
        return jsonify(payload)

    @app.before_request
    def _gate_until_module_ready():
        if request.path == "/api/health" or _module_ready:
            return None
        if SERVE_STATIC and not request.path.startswith("/api"):
            return None
        if request.path == "/api/stats":
            return jsonify(
                {
                    "qualified_count": 0,
                    "unqualified_count": 0,
                    "total_files": 0,
                    "parsed_files": 0,
                    "provinces": {},
                    "count_mode": "item",
                    "module_loading": True,
                    "cache_loading": True,
                    "message": "后端模块加载中，请稍候…",
                }
            )
        if request.path == "/api/status":
            return jsonify(
                {
                    "running": False,
                    "progress": 0,
                    "total": 0,
                    "message": "后端模块加载中，请稍候…",
                    "has_cache": os.path.isfile(CACHE_FILE),
                    "pending_new": 0,
                    "pending_checking": False,
                    "module_loading": True,
                    "cache_loading": True,
                    "auto_scan_interval_sec": AUTO_SCAN_INTERVAL_SEC,
                }
            )
        return jsonify({"ok": False, "message": "后端模块加载中，请稍候…", "loading": True}), 503

    if SERVE_STATIC:
        _register_static_routes(app)

    try:
        print("[启动] 正在加载 pandas / 解析库并注册 API 路由…", flush=True)
        from food_inspection.web.routes import register_routes

        with _module_lock:
            register_routes(app)
        print("[启动] API 路由已注册，正在后台加载数据缓存…", flush=True)
    except Exception as exc:
        _module_error = str(exc)
        print(f"[错误] 路由注册失败: {exc}", flush=True)
        traceback.print_exc()
        return app

    def _load_data_cache() -> None:
        global _module_ready, _module_error
        try:
            from food_inspection import store

            with _module_lock:
                store.bootstrap()
                store.schedule_startup_auto_scan()
                _module_ready = True
            print("[后台] 数据模块已就绪。", flush=True)
        except Exception as exc:
            _module_error = str(exc)
            print(f"[错误] 数据加载失败: {exc}", flush=True)
            traceback.print_exc()

    threading.Thread(target=_load_data_cache, daemon=True, name="module-load").start()
    return app


def _register_static_routes(app: Flask) -> None:
    if not os.path.isdir(STATIC_DIR):
        print(f"[警告] 前端静态目录不存在: {STATIC_DIR}，请先执行 npm run build", flush=True)
        return

    index_html = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_html):
        print(f"[警告] 缺少 {index_html}，请先执行 npm run build", flush=True)
        return

    print(f"[生产] 托管前端静态资源: {STATIC_DIR}", flush=True)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path: str):
        if path.startswith("api/"):
            abort(404)
        if path:
            file_path = os.path.join(STATIC_DIR, path)
            if os.path.isfile(file_path):
                return send_from_directory(STATIC_DIR, path)
        return send_file(index_html)
