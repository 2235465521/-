#!/usr/bin/env bash
# 生产环境一键启动：构建前端 + Gunicorn 单端口服务
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -f "$ROOT/deploy.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/deploy.env"
  set +a
fi

export PRODUCTION=1
export SERVE_STATIC=1

is_port_in_use() {
  "$PYTHON_BIN" - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", port))
except OSError:
    sys.exit(0)
else:
    sys.exit(1)
finally:
    s.close()
PY
}

pick_port() {
  local preferred="${1:-8080}"
  local port="$preferred"
  local limit=$((preferred + 100))
  while [ "$port" -lt "$limit" ]; do
    if ! is_port_in_use "$port"; then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
  done
  echo "[错误] ${preferred}~$((limit - 1)) 范围内无空闲端口，请手动指定 APP_PORT" >&2
  return 1
}

resolve_python() {
  if [ -n "${PYTHON:-}" ]; then
    echo "$PYTHON"
    return
  fi
  if command -v conda >/dev/null 2>&1; then
    local conda_py
    conda_py="$(conda run -n chouchafenxi which python 2>/dev/null || true)"
    if [ -n "$conda_py" ]; then
      echo "$conda_py"
      return
    fi
  fi
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
    return
  fi
  command -v python3
}

PYTHON_BIN="$(resolve_python)"

PREFERRED_PORT="${APP_PORT:-8080}"
if [ -n "${APP_PORT:-}" ]; then
  if is_port_in_use "$APP_PORT"; then
    echo "[错误] 指定端口 ${APP_PORT} 已被占用，请换一个端口，例如: APP_PORT=8090 ./start-prod.sh" >&2
    exit 1
  fi
  APP_PORT="$APP_PORT"
else
  APP_PORT="$(pick_port "$PREFERRED_PORT")"
  if is_port_in_use "$PREFERRED_PORT"; then
    echo "[提示] 默认端口 ${PREFERRED_PORT} 已被占用，改用 ${APP_PORT}"
  fi
fi
export APP_PORT

echo "==> 构建前端..."
cd "$ROOT/frontend"
npm run build

echo "==> 启动生产服务 http://${APP_HOST}:${APP_PORT}"
echo "    数据目录: ${DATA_ROOT}"
cd "$ROOT/backend"
exec "$PYTHON_BIN" -m gunicorn \
  -w 1 \
  -b "${APP_HOST}:${APP_PORT}" \
  --threads 8 \
  --timeout 300 \
  --access-logfile - \
  "app:app"
