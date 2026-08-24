#!/usr/bin/env bash
# 更新预发 Nginx：8093 -> 127.0.0.1:8008
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF_SRC="$ROOT/deploy/nginx-shiping-staging.conf"
CONF_DST="/etc/nginx/conf.d/shipingchoucha-staging.conf"

if [[ ! -f "$CONF_SRC" ]]; then
  echo "缺少 $CONF_SRC"
  exit 1
fi

sudo cp "$CONF_SRC" "$CONF_DST"
sudo nginx -t
sudo systemctl reload nginx
echo "Nginx 预发已重载：8093 -> 127.0.0.1:8008"
