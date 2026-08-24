"""食品安全监督抽查数据统计 Web 应用入口。"""

from __future__ import annotations

import os
import sys


def _serve_production() -> None:
    from config import APP_HOST, APP_PORT

    workers = max(1, int(os.environ.get("GUNICORN_WORKERS", "2")))
    threads = max(1, int(os.environ.get("GUNICORN_THREADS", "4")))

    if sys.platform == "win32":
        from waitress import serve

        print("[生产] 使用 Waitress 启动", flush=True)
        serve(app, host=APP_HOST, port=APP_PORT, threads=8)
        return

    try:
        from gunicorn.app.wsgiapp import run
    except ImportError as exc:
        raise RuntimeError("生产模式需要安装 gunicorn：pip install gunicorn") from exc

    print(f"[生产] 使用 Gunicorn 启动（workers={workers}, threads={threads}）", flush=True)
    sys.argv = [
        "gunicorn",
        "-w",
        str(workers),
        "-b",
        f"{APP_HOST}:{APP_PORT}",
        "--threads",
        str(threads),
        "--timeout",
        "300",
        "--graceful-timeout",
        "30",
        "--access-logfile",
        "-",
        "app:app",
    ]
    run()


def main() -> None:
    from config import APP_HOST, APP_PORT, PRODUCTION, SERVE_STATIC

    print("=" * 48, flush=True)
    print("  食品安全监督抽检统计 - 后端", flush=True)
    print("=" * 48, flush=True)
    url = f"http://{APP_HOST}:{APP_PORT}"
    print(f"Web 服务将监听 {url}", flush=True)
    if SERVE_STATIC:
        print("生产模式：前后端同端口，访问上述地址即可打开页面。", flush=True)
    else:
        print("开发模式：pandas 等重模块在后台加载，前端可先打开。", flush=True)
    print("-" * 48, flush=True)

    if PRODUCTION:
        # 由 Gunicorn 导入 app:app 并创建实例，避免重复初始化
        _serve_production()
        return

    from food_inspection.web.factory import create_app

    app = create_app()
    app.run(host=APP_HOST, port=APP_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
        sys.exit(0)
    except Exception as exc:
        print(f"\n[错误] 启动失败: {exc}", flush=True)
        import traceback

        traceback.print_exc()
        if sys.platform == "win32":
            input("\n按回车键关闭...")
        sys.exit(1)
else:
    from food_inspection.web.factory import create_app

    app = create_app()
