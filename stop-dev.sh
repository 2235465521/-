#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

stop_pid_file() {
  local file="$1"
  local name="$2"
  if [ -f "$file" ]; then
    local pid
    pid="$(cat "$file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "已停止 ${name} (PID ${pid})"
    else
      echo "${name} 未在运行 (PID ${pid})"
    fi
    rm -f "$file"
  fi
}

stop_project_processes() {
  local pattern="$1"
  local label="$2"
  local pid
  for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "已停止遗留 ${label} (PID ${pid})"
    fi
  done
}

stop_project_backend() {
  local pid cwd
  for pid in $(pgrep -f "python.*app\.py" 2>/dev/null || true); do
    cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
    if [ "$cwd" = "$ROOT/backend" ]; then
      kill "$pid" 2>/dev/null || true
      echo "已停止遗留 后端 (PID ${pid})"
    fi
  done
}

stop_pid_file "$ROOT/logs/backend-dev.pid" "后端"
stop_pid_file "$ROOT/logs/frontend-dev.pid" "前端"
stop_project_backend
stop_project_processes "${ROOT}/frontend/node_modules/.bin/vite" "前端 Vite"
rm -f "$ROOT/logs/dev-ports.env"
