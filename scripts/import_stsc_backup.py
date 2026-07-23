# -*- coding: utf-8 -*-
"""兼容入口：请改用 scripts/setup_mysql.py（启动脚本已自动调用）。"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("setup_mysql.py")), run_name="__main__")
