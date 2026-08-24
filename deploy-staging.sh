#!/usr/bin/env bash
# 预发环境部署：Nginx :8093 + PM2 shipin-backend-staging :8008
# 日常开发只跑本脚本，不影响生产 :8091 / shipin-backend :8006
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-/home/zkbz01/anaconda3/envs/chouchafenxi/bin/python}"
PM2_NAME="shipin-backend-staging"
STAGING_DIST="$ROOT/frontend/dist-staging"
STAGING_CACHE="$ROOT/backend/data/staging/analytics_disk_cache"

mkdir -p "$STAGING_CACHE"

echo "==> 同步省级地图 GeoJSON 到前端 public/geo..."
GEO_SRC="$ROOT/backend/geo_data"
GEO_DST="$ROOT/frontend/public/geo"
mkdir -p "$GEO_DST"
if compgen -G "$GEO_SRC/*_full.json" > /dev/null; then
  cp -u "$GEO_SRC"/*_full.json "$GEO_DST"/
fi

echo "==> 构建预发前端 dist-staging..."
cd "$ROOT/frontend"
npm run build -- --outDir dist-staging

echo "==> 安装/更新 Python 依赖（含 redis）..."
"$PYTHON_BIN" -m pip install -q redis

echo "==> 启动/重启预发后端 $PM2_NAME (:8008)..."
chmod +x "$ROOT/backend/run-staging.sh"
chmod +x "$ROOT/backend/run-staging-web.sh"
if pm2 describe "$PM2_NAME" >/dev/null 2>&1; then
  pm2 delete "$PM2_NAME" >/dev/null 2>&1 || true
fi
pm2 start "$ROOT/backend/run-staging.sh" \
  --name "$PM2_NAME" \
  --interpreter bash \
  --cwd "$ROOT/backend"

WEB_PM2_NAME="shipin-staging-web"
echo "==> 启动/重启预发 Web $WEB_PM2_NAME (:8093)..."
if pm2 describe "$WEB_PM2_NAME" >/dev/null 2>&1; then
  pm2 restart "$WEB_PM2_NAME" --update-env
else
  pm2 start "$ROOT/backend/run-staging-web.sh" \
    --name "$WEB_PM2_NAME" \
    --interpreter bash \
    --cwd "$ROOT/backend"
fi

echo ""
echo "预发部署完成！"
echo "  预发访问（内网）: http://$(hostname -I | awk '{print $1}'):8093"
echo "  预发访问（外网）: http://47.106.104.48:5178"
echo "  预发 API: http://127.0.0.1:8008（内部）"
echo "  生产访问: http://$(hostname -I | awk '{print $1}'):8091 （未改动）"
echo ""
echo "（可选）若需 Nginx 代理 8093，可执行: bash deploy/apply-nginx-staging.sh"
echo ""
echo "==> 预热省级地图/城市洞察缓存（后台低优先级，缓存齐全时跳过）..."
REGION_CACHE_DIR="$ROOT/backend/data/staging/region_disk_cache"
if [[ -d "$REGION_CACHE_DIR" ]] && [[ "$(find "$REGION_CACHE_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l)" -ge 60 ]]; then
  echo "  省级磁盘缓存已存在，跳过 region 预热"
else
  (
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/deploy.env"
    # shellcheck disable=SC1091
    source "$ROOT/deploy-staging.env"
    set +a
    cd "$ROOT/backend"
    nice -n 15 nohup "$PYTHON_BIN" -m scripts.warm_region_cache \
      >>"$ROOT/backend/data/staging/warm_region_cache.log" 2>&1 &
  )
fi

echo "==> 刷新预统计汇总表（stats_global / stats_region）..."
(
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/deploy.env"
  # shellcheck disable=SC1091
  source "$ROOT/deploy-staging.env"
  set +a
  cd "$ROOT/backend"
  "$PYTHON_BIN" -m scripts.refresh_stats \
    >>"$ROOT/backend/data/staging/refresh_stats.log" 2>&1 || true
)

echo "==> 同步磁盘缓存到 Redis（预发 db1）..."
(
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/deploy.env"
  # shellcheck disable=SC1091
  source "$ROOT/deploy-staging.env"
  set +a
  cd "$ROOT/backend"
  nice -n 15 "$PYTHON_BIN" -m scripts.warm_redis_cache \
    >>"$ROOT/backend/data/staging/warm_redis_cache.log" 2>&1 &
)

echo "验证: curl -s http://127.0.0.1:8093/api/health"
