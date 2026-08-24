#!/usr/bin/env bash
# 预发 Web 入口：8093 同时托管 dist-staging 与预发 API（无需 Nginx sudo）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

PYTHON_BIN="${PYTHON_BIN:-/home/zkbz01/anaconda3/envs/chouchafenxi/bin/python}"

set -a
# shellcheck disable=SC1091
source "$ROOT/deploy.env"
# shellcheck disable=SC1091
source "$ROOT/deploy-staging.env"
set +a

export PRODUCTION=1
export SERVE_STATIC=1
export STATIC_DIR="$ROOT/frontend/dist-staging"
export APP_HOST=0.0.0.0
export APP_PORT="${STAGING_WEB_PORT:-8093}"

exec "$PYTHON_BIN" app.py
