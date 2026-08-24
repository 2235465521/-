#!/usr/bin/env bash
# 生产环境部署（Nginx :8091 + PM2 shipin-backend :8006）
# 日常开发请用 deploy-staging.sh；确认无误后再 promote-to-prod.sh 发布生产
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "==> 拉取最新代码..."
git fetch origin
git checkout fenxi
git pull origin fenxi

echo "==> 构建前端 dist（Nginx 静态页面）..."
cd "$ROOT/frontend"
npm run build

echo "==> 重启 PM2 后端 shipin-backend..."
pm2 restart shipin-backend

echo ""
echo "可选：更新 Nginx API 超时（需 sudo）"
echo "  bash deploy/apply-nginx.sh"

echo ""
echo "部署完成！"
echo "  访问地址: http://$(hostname -I | awk '{print $1}'):8091"
echo "  后端 API: http://127.0.0.1:8006 (PM2)"
echo ""
echo "验证: curl -s http://127.0.0.1:8006/api/health"
