#!/usr/bin/env bash
# 更新 Nginx 配置：/api/health 短超时，其余 API 300s，避免 analytics 计算触发 502/504
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF_SRC="$ROOT/deploy/nginx-shiping.conf"
CONF_DST="/etc/nginx/conf.d/shipingchoucha.conf"

if [[ ! -f "$CONF_SRC" ]]; then
  echo "缺少 $CONF_SRC"
  exit 1
fi

sudo cp "$CONF_SRC" "$CONF_DST"
sudo nginx -t
sudo systemctl reload nginx
echo "Nginx 已重载：8091 -> 127.0.0.1:8006（API 超时 300s，health 5s）"
