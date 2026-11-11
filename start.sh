#!/usr/bin/env bash
# 标准 PDF 下载项目 - Linux 启动/重启脚本
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=== 正在检查 PM2 服务状态 ==="
if command -v pm2 >/dev/null 2>&1; then
    if pm2 describe downloadfile-backend >/dev/null 2>&1; then
        echo "重启已存在的 PM2 服务: downloadfile-backend"
        pm2 restart downloadfile-backend
    else
        echo "启动新的 PM2 服务: downloadfile-backend"
        pm2 start /home/zkbz01/anaconda3/envs/download_file/bin/gunicorn \
            --name "downloadfile-backend" \
            -- --workers 3 --bind 127.0.0.1:8005 backend.app:app --timeout 600
    fi
    echo ""
    echo "服务已通过 PM2 启动！"
    echo "访问地址: http://192.168.10.225:8090/ (或 http://127.0.0.1:8090/)"
else
    echo "未找到 PM2，尝试使用 conda 环境直接启动："
    /home/zkbz01/anaconda3/envs/download_file/bin/python backend/run.py
fi
