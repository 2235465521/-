#!/usr/bin/env bash
# 生产后端 PM2 入口：加载 deploy.env 后启动 Gunicorn（:8006，Nginx :8091 反代）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

PYTHON_BIN="${PYTHON_BIN:-/home/zkbz01/anaconda3/envs/chouchafenxi/bin/python}"

set -a
# shellcheck disable=SC1091
source "$ROOT/deploy.env"
set +a

export PRODUCTION=1
export APP_PORT="${APP_PORT:-8006}"
exec "$PYTHON_BIN" app.py
