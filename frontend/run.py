#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 8080
FRONTEND_DIR = Path(__file__).resolve().parent
URL = f"http://127.0.0.1:{PORT}"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> None:
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("=" * 50)
        print("  PDF 下载 · 纯前端")
        print(f"  地址: {URL}")
        print("  关闭本窗口即停止服务")
        print("=" * 50)
        webbrowser.open(URL)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")


if __name__ == "__main__":
    main()
