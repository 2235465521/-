#!/usr/bin/env bash
# 开发模式：后端 Flask + 前端 Vite（两个端口，支持热更新）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# 启动前先清理旧进程，避免多端口遗留后端（如 8006）返回旧数据
"$ROOT/stop-dev.sh" >/dev/null 2>&1 || true

if [ -f "$ROOT/deploy.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/deploy.env"
  set +a
fi

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
  local preferred="$1"
  local port="$preferred"
  local limit=$((preferred + 20))
  while [ "$port" -lt "$limit" ]; do
    if ! is_port_in_use "$port"; then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
  done
  echo "[错误] ${preferred}~$((limit - 1)) 无空闲端口" >&2
  return 1
}

BACKEND_PORT="${APP_PORT:-8080}"
if is_port_in_use "$BACKEND_PORT"; then
  NEW_PORT="$(pick_port "$BACKEND_PORT")"
  echo "[提示] 后端端口 ${BACKEND_PORT} 已占用，改用 ${NEW_PORT}"
  BACKEND_PORT="$NEW_PORT"
fi

FRONTEND_PORT="${VITE_PORT:-5173}"
if is_port_in_use "$FRONTEND_PORT"; then
  NEW_FE="$(pick_port "$FRONTEND_PORT")"
  echo "[提示] 前端端口 ${FRONTEND_PORT} 已占用，改用 ${NEW_FE}"
  FRONTEND_PORT="$NEW_FE"
fi

export APP_HOST="${APP_HOST:-0.0.0.0}"
export APP_PORT="$BACKEND_PORT"

mkdir -p "$ROOT/logs"

echo "==> 启动后端开发服务 :${BACKEND_PORT}"
cd "$ROOT/backend"
nohup "$PYTHON_BIN" app.py > "$ROOT/logs/backend-dev.log" 2>&1 &
BACKEND_PID=$!

echo "==> 启动前端开发服务 :${FRONTEND_PORT}"
cd "$ROOT/frontend"
# 走 Vite 代理 /api，便于从局域网其他电脑访问
export VITE_API_BASE=
nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" > "$ROOT/logs/frontend-dev.log" 2>&1 &
FRONTEND_PID=$!

echo "$BACKEND_PID" > "$ROOT/logs/backend-dev.pid"
echo "$FRONTEND_PID" > "$ROOT/logs/frontend-dev.pid"

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "$LAN_IP" ]; then
  LAN_IP="127.0.0.1"
fi

cat > "$ROOT/logs/dev-ports.env" <<EOF
BACKEND_PORT=${BACKEND_PORT}
FRONTEND_PORT=${FRONTEND_PORT}
LAN_IP=${LAN_IP}
FRONTEND_URL=http://${LAN_IP}:${FRONTEND_PORT}
BACKEND_URL=http://${LAN_IP}:${BACKEND_PORT}
EOF

sleep 2

echo ""
echo "开发服务已启动："
echo "  前端页面  http://${LAN_IP}:${FRONTEND_PORT}"
echo "  后端 API  http://${LAN_IP}:${BACKEND_PORT}"
echo "  日志      logs/backend-dev.log  logs/frontend-dev.log"
echo ""
echo "其他电脑访问请用上面的局域网 IP，不要用 127.0.0.1"
echo "端口信息已写入 logs/dev-ports.env"
echo ""
echo "停止服务："
echo "  ./stop-dev.sh"
