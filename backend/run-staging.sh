#!/usr/bin/env bash
# PM2 预发后端入口：加载 deploy.env + deploy-staging.env 后启动
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

echo "[staging-env] MYSQL_HOST=${MYSQL_HOST:-} MYSQL_PORT=${MYSQL_PORT:-} MYSQL_USER=${MYSQL_USER:-} MYSQL_DATABASE=${MYSQL_DATABASE:-} MYSQL_TABLE=${MYSQL_TABLE:-} USE_MYSQL=${USE_MYSQL:-}"
export PRODUCTION=1
exec "$PYTHON_BIN" app.py
