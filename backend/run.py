#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动后端服务（默认 http://127.0.0.1:5000）。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app import main

if __name__ == "__main__":
    main()
