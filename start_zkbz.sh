#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PY=""
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo " [错误] 未找到 Python 3"
  exit 1
fi

echo " 检查运行依赖…"
if ! $PY -c "import flask, pymysql, dotenv" >/dev/null 2>&1; then
  echo " 首次或缺包，正在安装 requirements.txt …"
  $PY -m pip install -r requirements.txt
fi

echo " 检查 / 准备 MySQL 标准库…"
if ! $PY scripts/setup_mysql.py; then
  echo " [错误] 标准库未就绪"
  echo " 请确认 MySQL 已启动、.env 账号正确，且 data/db_dump/ 含 *.sql.gz"
  echo " 也可: docker compose up -d mysql  （默认 root/zkbz）"
  exit 1
fi

echo ""
echo " ========================================"
echo "   ZKBZ 标准PDF下载"
echo "   地址: http://127.0.0.1:5000/"
echo "   请勿关闭本窗口 - 关闭即停止服务"
echo " ========================================"
echo ""

exec $PY backend/run.py
