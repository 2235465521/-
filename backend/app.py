"""标准 PDF 批量下载 — Flask API + 前端静态页。"""
from __future__ import annotations

import json
import mimetypes
import sys
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND = _ROOT / "frontend"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import (  # noqa: E402
    ALLOW_REGISTER,
    APP_VERSION,
    HOST,
    OPEN_BROWSER,
    PORT,
    SECRET_KEY,
    SESSION_DAYS,
)
from core.auth import (  # noqa: E402
    DEFAULT_USER_PASS,
    DEFAULT_USER_USER,
    authenticate,
    create_user,
    current_user,
    ensure_auth_schema,
    list_users,
    login_user,
    logout_user,
    require_admin,
    require_login,
    update_user,
    ROLE_USER,
)
from core.batch_download import (  # noqa: E402
    build_template_xlsx,
    build_zip_archive,
    build_zip_from_base_ids,
    build_zip_from_geo,
    parse_upload,
    preview_items,
)
from core.geo_download import count_geo_matches, geo_download_status  # noqa: E402
from core.area_lookup import suggest_companies  # noqa: E402
from core.db import StandardInfo, db  # noqa: E402
from core.pdf_service import collect_files_for_standard, find_pdf_on_disk  # noqa: E402
from core.product_clusters import list_clusters_brief  # noqa: E402
from core.product_search import product_search  # noqa: E402
from core.search_filters import (  # noqa: E402
    filter_options_payload,
    parse_advanced_filters,
    parse_workflow,
    validate_search_workflow,
)
from core.std_normalize import db_filepath_matches_std  # noqa: E402
from paths import PDF_ROOT, PDF_SEARCH_ROOT  # noqa: E402

app = Flask(__name__, static_folder=None)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=max(1, SESSION_DAYS)),
)

# 无需登录即可访问的 API
_PUBLIC_API_PREFIXES = (
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/register",
    "/api/meta/health",
)


@app.before_request
def _require_api_login():
    path = request.path or ""
    if not path.startswith("/api/"):
        return None
    if any(path == p or path.startswith(p + "/") for p in _PUBLIC_API_PREFIXES):
        return None
    user = current_user()
    if not user:
        return jsonify({"ok": False, "error": "请先登录", "code": "auth_required"}), 401
    return None


try:
    ensure_auth_schema()
except Exception as _auth_init_err:  # noqa: BLE001
    print(f"  [警告] 用户表初始化失败: {_auth_init_err}")


def _api_error(message: str, status: int = 500):
    return jsonify({"ok": False, "error": message}), status


@app.errorhandler(404)
def api_not_found(e):
    if request.path.startswith("/api/"):
        return _api_error("接口不存在", 404)
    return e


@app.errorhandler(500)
def api_server_error(e):
    if request.path.startswith("/api/"):
        return _api_error("服务器内部错误，请稍后重试")
    return e


@app.after_request
def _no_cache_html(resp):
    if request.path.endswith(".html") or request.path in ("/", ""):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


def create_app() -> Flask:
    return app


def _standard_json(std: StandardInfo) -> dict:
    files = collect_files_for_standard(std)
    return {
        "id": std.id,
        "std_id": std.std_id,
        "std_type": std.std_type,
        "std_chinesename": std.std_chinesename,
        "std_status": std.std_status,
        "ex_state": std.ex_state,
        "ex_state_label": std.ex_state_label,
        "release_date": std.release_date,
        "implement_date": std.implement_date,
        "files": [
            {
                "id": f.get("id"),
                "file_name": f.get("file_name"),
                "file_path": f.get("file_path"),
                "file_size": f.get("file_size"),
                "exists": bool(f.get("exists")),
                "source": f.get("source", "db"),
            }
            for f in files
        ],
    }


def _enrich_items(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for it in items:
        std = db.get_by_id(int(it["id"]))
        if not std:
            out.append(it)
            continue
        full = _standard_json(std)
        # 与列表 has_pdf 一致：存在与标准号（含年份）匹配的 PDF 记录即可
        full["has_pdf"] = bool(full.get("files"))
        out.append(full)
    return out


@app.route("/api/search")
def api_search():
    try:
        q = (request.args.get("q") or "").strip()
        src = (request.args.get("source") or "").strip()
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(1, int(request.args.get("per_page", 10))))
        pdf_only = request.args.get("pdf_only", "1") != "0"
        enrich = request.args.get("enrich", "0") == "1"

        if not db.is_ready():
            return jsonify({"ok": False, "error": "标准库未就绪：请配置 .env 中的 MySQL，并导入标准库备份后重启服务"}), 503

        if src == "product":
            if not q:
                return jsonify({"ok": False, "error": "请输入产品名称，如：牙膏"}), 400
            data = product_search.search_page(
                q, page=page, per_page=per_page, pdf_only=pdf_only
            )
            if data.get("error"):
                return jsonify({"ok": False, "error": data["error"]}), 400
            if enrich:
                data["items"] = _enrich_items(data.get("items") or [])
            return jsonify({"ok": True, "query": q, **data})

        filters = parse_advanced_filters(request.args)
        workflow = parse_workflow(request.args.get("workflow"))
        wf_err = validate_search_workflow(workflow, q=q, filters=filters)
        if wf_err:
            return jsonify({"ok": False, "error": wf_err, "workflow": workflow}), 400

        if not q and not filters.active():
            return jsonify({"ok": False, "error": "请输入关键词或设置高级筛选条件"}), 400

        from core.unit_geo import needs_geo_filter

        if needs_geo_filter(filters) and not db._mysql_available():
            return jsonify(
                {
                    "ok": False,
                    "error": "省/市/县/起草单位筛选需 MySQL 标准库（含 area_dict / unit_dict）",
                }
            ), 503

        if (filters.unit_rank is not None or filters.unit_rank_gt3) and not filters.company:
            return jsonify(
                {
                    "ok": False,
                    "error": "「起草顺位」需同时填写「公司/起草单位」，否则无法按排序筛选",
                }
            ), 400

        if filters.active() or request.args.get("advanced") == "1":
            data = db.search_page_advanced(
                q,
                page=page,
                per_page=per_page,
                pdf_only=pdf_only,
                filters=filters,
            )
        else:
            data = db.search_page(q, page=page, per_page=per_page, pdf_only=pdf_only)

        if enrich:
            data["items"] = _enrich_items(data.get("items") or [])
        return jsonify({"ok": True, "query": q, "workflow": workflow, **data})
    except ValueError:
        return jsonify({"ok": False, "error": "请求参数无效"}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"检索失败：{exc}"}), 500


@app.route("/api/search/filters")
def api_search_filters():
    province = (request.args.get("province") or "").strip()
    city = (request.args.get("city") or "").strip()
    company_q = (request.args.get("company_q") or "").strip()
    product_q = (request.args.get("product_q") or "").strip()
    from core import area_lookup
    from core.product_clusters import list_clusters_brief, suggest_phrases

    if company_q and not province and not city and not product_q:
        return jsonify({"ok": True, "companies": suggest_companies(company_q)})
    if product_q and not province and not city and not company_q:
        return jsonify(
            {
                "ok": True,
                "products": list_clusters_brief(),
                "product_suggestions": suggest_phrases(product_q, limit=16),
            }
        )

    products = list_clusters_brief()
    payload = filter_options_payload(
        std_types=db.list_std_types() if db.is_ready() else [],
        provinces=area_lookup.list_provinces(),
        cities=area_lookup.list_cities(province) if province else [],
        counties=area_lookup.list_counties(province, city) if province and city else [],
        products=products,
        companies=suggest_companies(company_q) if company_q else [],
        product_suggestions=suggest_phrases(product_q, limit=16) if product_q else [],
    )
    return jsonify({"ok": True, **payload})


@app.route("/api/product/clusters")
def api_product_clusters():
    return jsonify(
        {
            "ok": True,
            "clusters": product_search.list_clusters(),
            "ready": product_search.is_ready(),
            "describe": product_search.describe(),
        }
    )


@app.route("/api/download/geo/preview")
def api_download_geo_preview():
    filters = parse_advanced_filters(request.args)
    q = (request.args.get("q") or "").strip()
    pdf_only = request.args.get("pdf_only", "1") != "0"
    if not filters.province:
        return jsonify({"ok": False, "error": "请选择省份"}), 400
    if not geo_download_status()["ready"]:
        return jsonify(
            {
                "ok": False,
                "error": "地区批量下载未就绪，请配置 MySQL 标准库",
            }
        ), 503
    payload = count_geo_matches(filters, q=q, pdf_only=pdf_only)
    status = 200 if payload.get("ok") else 400
    return jsonify(payload), status


@app.route("/api/download/geo", methods=["POST"])
def api_download_geo():
    body = request.get_json(silent=True) or {}
    filters = parse_advanced_filters(body)
    q = (body.get("q") or "").strip()
    pdf_only = body.get("pdf_only", True) in (True, 1, "1", "true")
    if not filters.province:
        return jsonify({"ok": False, "error": "请选择省份"}), 400
    if not geo_download_status()["ready"]:
        return jsonify(
            {
                "ok": False,
                "error": "地区批量下载未就绪，请配置 MySQL 标准库",
            }
        ), 503
    preview = count_geo_matches(filters, q=q, pdf_only=pdf_only)
    if not preview.get("ok"):
        return jsonify(preview), 400
    if preview.get("total", 0) < 1:
        return jsonify({"ok": False, "error": "当前条件下未找到可下载标准", **preview}), 404
    try:
        buf, summary = build_zip_from_geo(filters, q=q, pdf_only=pdf_only)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    if summary.get("success", 0) < 1:
        return jsonify(
            {
                "ok": False,
                "error": "未找到任何可打包的 PDF",
                "summary": summary,
                **preview,
            }
        ), 404
    region = preview.get("region") or "地区"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"地区批量下载_{region}_{stamp}.zip",
    )


@app.route("/api/download/bulk", methods=["POST"])
def api_download_bulk():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or data.get("base_ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "请勾选要下载的条目"}), 400
    try:
        buf, summary = build_zip_from_base_ids(ids)
        zip_label = "标准PDF多项下载"
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    if summary.get("success", 0) < 1:
        return jsonify(
            {
                "ok": False,
                "error": "所选条目均未找到可用文件",
                "summary": summary,
            }
        ), 404
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{zip_label}_{stamp}.zip",
    )


@app.route("/api/std/<int:base_id>")
def api_std_detail(base_id: int):
    std = db.get_by_id(base_id)
    if not std:
        return jsonify({"ok": False, "error": "未找到该标准"}), 404
    return jsonify({"ok": True, "item": _standard_json(std)})


@app.route("/api/download/<int:file_id>")
def api_download_file(file_id: int):
    rec = db.get_filepath_record(file_id)
    if not rec:
        return jsonify({"ok": False, "error": "文件记录不存在"}), 404
    std = db.get_by_id(rec["base_id"])
    if std and not db_filepath_matches_std(
        std.std_id or "", rec.get("file_name"), rec.get("file_path")
    ):
        return jsonify({"ok": False, "error": "该文件与当前标准版本不匹配"}), 404
    found = find_pdf_on_disk(
        rec.get("file_path") or "",
        rec.get("file_name") or "",
    )
    if not found or not found.is_file():
        return jsonify({"ok": False, "error": "磁盘上未找到 PDF 文件"}), 404
    return send_file(found, as_attachment=True, download_name=found.name)


# ---------- 鉴权 ----------


@app.route("/api/auth/me")
def api_auth_me():
    user = current_user()
    return jsonify(
        {
            "ok": True,
            "authenticated": bool(user),
            "user": user.to_public() if user else None,
            "allow_register": ALLOW_REGISTER,
        }
    )


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "请输入用户名和密码"}), 400
    try:
        user = authenticate(username, password)
    except Exception as e:  # noqa: BLE001
        return _api_error(f"登录失败：{e}"), 503
    if not user:
        return jsonify({"ok": False, "error": "用户名或密码错误，或账号已停用"}), 401
    login_user(user)
    return jsonify({"ok": True, "user": user.to_public()})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    if not ALLOW_REGISTER:
        return jsonify({"ok": False, "error": "当前未开放自行注册"}), 403
    body = request.get_json(silent=True) or {}
    try:
        user, err = create_user(
            username=body.get("username") or "",
            password=body.get("password") or "",
            display_name=body.get("display_name") or "",
            role=ROLE_USER,
        )
    except Exception as e:  # noqa: BLE001
        return _api_error(f"注册失败：{e}"), 503
    if err:
        return jsonify({"ok": False, "error": err}), 400
    login_user(user)
    return jsonify({"ok": True, "user": user.to_public()})


@app.route("/api/auth/change-password", methods=["POST"])
@require_login
def api_auth_change_password():
    body = request.get_json(silent=True) or {}
    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""
    user = current_user()
    if not user:
        return jsonify({"ok": False, "error": "请先登录", "code": "auth_required"}), 401
    check = authenticate(user.username, old_password)
    if not check:
        return jsonify({"ok": False, "error": "原密码不正确"}), 400
    updated, err = update_user(user.id, password=new_password, actor_id=user.id)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "user": updated.to_public()})


@app.route("/api/admin/users")
@require_admin
def api_admin_users():
    q = (request.args.get("q") or "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    try:
        return jsonify(list_users(q=q, page=page, per_page=per_page))
    except Exception as e:  # noqa: BLE001
        return _api_error(f"查询用户失败：{e}")


@app.route("/api/admin/users", methods=["POST"])
@require_admin
def api_admin_create_user():
    body = request.get_json(silent=True) or {}
    user, err = create_user(
        username=body.get("username") or "",
        password=body.get("password") or "",
        display_name=body.get("display_name") or "",
        role=body.get("role") or ROLE_USER,
    )
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "user": user.to_public()})


@app.route("/api/admin/users/<int:user_id>", methods=["PATCH"])
@require_admin
def api_admin_update_user(user_id: int):
    body = request.get_json(silent=True) or {}
    actor = current_user()
    kwargs = {}
    if "display_name" in body:
        kwargs["display_name"] = body.get("display_name")
    if "role" in body:
        kwargs["role"] = body.get("role")
    if "is_active" in body:
        kwargs["is_active"] = bool(body.get("is_active"))
    if body.get("password"):
        kwargs["password"] = body.get("password")
    updated, err = update_user(user_id, actor_id=actor.id if actor else None, **kwargs)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "user": updated.to_public()})


@app.route("/")
def index_page():
    return send_from_directory(_FRONTEND, "index.html")


@app.route("/login")
@app.route("/login.html")
def login_page():
    return send_from_directory(_FRONTEND, "login.html")


@app.route("/admin")
@app.route("/admin.html")
def admin_page():
    return send_from_directory(_FRONTEND, "admin.html")


@app.route("/css/<path:filename>")
def static_css(filename: str):
    return send_from_directory(_FRONTEND / "css", filename)


@app.route("/js/<path:filename>")
def static_js(filename: str):
    return send_from_directory(_FRONTEND / "js", filename)


@app.route("/api/meta/health")
def api_health():
    return jsonify(
        {
            "ok": True,
            "version": APP_VERSION,
            "db_ready": db.is_ready(),
            "db_backend": db.backend_name(),
            "geo_download": geo_download_status(),
            "pdf_root": str(PDF_ROOT),
            "pdf_root_exists": PDF_ROOT.is_dir(),
            "pdf_search_root": str(PDF_SEARCH_ROOT),
            "pdf_search_exists": PDF_SEARCH_ROOT.is_dir(),
            "allow_register": ALLOW_REGISTER,
        }
    )


@app.route("/api/batch/template")
def api_batch_template():
    data = build_template_xlsx()
    return send_file(
        __import__("io").BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="标准批量下载模板.xlsx",
    )


@app.route("/api/batch/parse", methods=["POST"])
def api_batch_parse():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "请上传 Excel 或 CSV 文件"}), 400
    data = upload.read()
    if not data:
        return jsonify({"ok": False, "error": "文件为空"}), 400
    if len(data) > 20 * 1024 * 1024:
        return jsonify({"ok": False, "error": "文件过大（上限 20MB）"}), 400
    result = parse_upload(upload.filename, data)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/batch/preview", methods=["POST"])
def api_batch_preview():
    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    if not items:
        return jsonify({"ok": False, "error": "无待预览条目"}), 400
    if not db.is_ready():
        return jsonify({"ok": False, "error": "标准库未就绪：请配置 .env 中的 MySQL，并导入标准库备份后重启服务"}), 503
    return jsonify(preview_items(items))


@app.route("/api/batch/download", methods=["POST"])
def api_batch_download():
    items: list[dict] = []
    original_data: bytes | None = None
    original_filename: str | None = None
    parse_meta: dict | None = None

    if request.files.get("file"):
        upload = request.files["file"]
        original_filename = upload.filename or "upload.xlsx"
        original_data = upload.read()
        parsed = parse_upload(original_filename, original_data)
        if not parsed.get("ok"):
            return jsonify(parsed), 400
        parse_meta = parsed.get("meta")
        items = parsed.get("items") or []
        form_items = request.form.get("items")
        if form_items:
            try:
                items = json.loads(form_items)
            except json.JSONDecodeError:
                pass
    else:
        body = request.get_json(silent=True) or {}
        items = body.get("items") or []

    if not items:
        return jsonify({"ok": False, "error": "无待下载条目"}), 400

    if not db.is_ready():
        return jsonify({"ok": False, "error": "标准库未就绪：请配置 .env 中的 MySQL，并导入标准库备份后重启服务"}), 503

    buf, summary = build_zip_archive(
        items,
        original_data=original_data,
        original_filename=original_filename,
        parse_meta=parse_meta,
    )
    if summary["success"] < 1:
        return jsonify({"ok": False, "error": "未找到任何可打包的 PDF", "summary": summary}), 404

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"标准PDF批量下载_{stamp}.zip",
    )


def main() -> None:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    try:
        ensure_auth_schema()
    except Exception as e:  # noqa: BLE001
        print(f"  [警告] 用户表初始化失败: {e}")
    url = f"http://127.0.0.1:{PORT}/login"
    print()
    print("  ========================================")
    print(f"    PDF 下载  v{APP_VERSION}")
    print(f"    浏览器打开: {url}")
    print(f"    数据库: {db.backend_name()}  PDF根目录: {PDF_ROOT}")
    print(f"    默认普通用户: {DEFAULT_USER_USER} / {DEFAULT_USER_PASS}")
    if not db.is_ready():
        print("    [提示] 标准库未就绪，请检查 .env 中的 MySQL 配置")
    if not PDF_ROOT.is_dir():
        print(f"    [提示] PDF 目录不存在，请检查 paths.py 或 .env 中的 PDF_ROOT")
    print("    请勿关闭本窗口")
    print("  ========================================")
    print()
    if OPEN_BROWSER:
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
