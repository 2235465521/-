#!/usr/bin/env bash
# 生产环境部署：同步地图 GeoJSON、构建前端、预热省级缓存、PM2 启动 shipin-backend (:8006)
# Nginx :8091 反代 API；静态资源由 Nginx 托管 frontend/dist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-/home/zkbz01/anaconda3/envs/chouchafenxi/bin/python}"
PM2_NAME="shipin-backend"
PROD_DIST="$ROOT/frontend/dist"
GEO_SRC="$ROOT/backend/geo_data"
GEO_DST="$ROOT/frontend/public/geo"
REGION_CACHE_DIR="$ROOT/backend/data/region_disk_cache"

echo "==> 同步省级地图 GeoJSON 到前端 public/geo..."
mkdir -p "$GEO_DST" "$REGION_CACHE_DIR"
if compgen -G "$GEO_SRC/*_full.json" > /dev/null; then
  cp -u "$GEO_SRC"/*_full.json "$GEO_DST"/
fi

if [[ -d "$ROOT/frontend/dist-staging" ]]; then
  echo "==> 同步预发前端 dist-staging -> 生产 dist（含地图修复）..."
  rm -rf "$PROD_DIST"
  cp -a "$ROOT/frontend/dist-staging" "$PROD_DIST"
else
  echo "==> 构建生产前端 dist..."
  cd "$ROOT/frontend"
  npm run build
fi

chmod +x "$ROOT/backend/run-prod.sh"

echo "==> 安装/更新 Python 依赖（含 redis）..."
"$PYTHON_BIN" -m pip install -q redis

echo "==> 启动/重启生产后端 $PM2_NAME (:8006)..."
if pm2 describe "$PM2_NAME" >/dev/null 2>&1; then
  pm2 delete "$PM2_NAME" >/dev/null 2>&1 || true
fi
pm2 start "$ROOT/backend/run-prod.sh" \
  --name "$PM2_NAME" \
  --interpreter bash \
  --cwd "$ROOT/backend"

echo "==> 确保 MySQL 列表索引..."
"$PYTHON_BIN" -m scripts.ensure_mysql_indexes \
  >>"$ROOT/backend/data/ensure_mysql_indexes.log" 2>&1 || true

echo "==> 刷新预统计汇总表（stats_global / stats_region / stats_rank_cache）..."
if [[ "${SKIP_STATS_REFRESH:-}" == "1" ]]; then
  echo "    跳过（SKIP_STATS_REFRESH=1，沿用当前 stats_rank_cache）"
else
(
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/deploy.env"
  set +a
  cd "$ROOT/backend"
  "$PYTHON_BIN" -m scripts.refresh_stats
) >>"$ROOT/backend/data/refresh_stats.log" 2>&1 || true
fi

echo "==> 预热 Redis + 省级地图缓存（后台低优先级）..."
(
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/deploy.env"
  set +a
  cd "$ROOT/backend"
  nice -n 15 nohup "$PYTHON_BIN" -m scripts.warm_region_cache \
    >>"$ROOT/backend/data/warm_region_cache.log" 2>&1 &
  nice -n 15 "$PYTHON_BIN" -m scripts.warm_redis_cache \
    >>"$ROOT/backend/data/warm_redis_cache.log" 2>&1 &
)

echo ""
echo "生产部署完成！"
echo "  访问: http://$(hostname -I | awk '{print $1}'):8091"
echo "  API:  http://127.0.0.1:8006"
echo ""
echo "验证:"
echo "  curl -s http://127.0.0.1:8006/api/health"
echo "  curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/geo/350000_full.json"
