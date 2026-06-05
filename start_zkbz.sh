#!/bin/bash

# 获取脚本所在目录，并切换到该目录
SCRIPTPATH="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
cd "$SCRIPTPATH"

echo "========================================"
echo "  ZKBZ 标准PDF下载 Linux 启动脚本"
echo "========================================"

# 检测 Python3
PY=""
if command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
fi

if [ -z "$PY" ]; then
    echo " [错误] 未找到 Python"
    echo " 请先在系统上安装 Python 3"
    exit 1
fi

# 释放 5000 端口
echo " 正在释放 5000 端口..."
if command -v fuser >/dev/null 2>&1; then
    fuser -k 5000/tcp >/dev/null 2>&1
elif command -v lsof >/dev/null 2>&1; then
    kill -9 $(lsof -t -i:5000) >/dev/null 2>&1
fi

# 检查运行依赖
echo " 检查运行依赖..."
$PY -c "import flask, pymysql, dotenv, openpyxl" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo " 首次或缺包，正在安装 requirements.txt ..."
    $PY -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo " [错误] 依赖安装失败，请检查网络或 Python 环境"
        exit 1
    fi
fi

# 检查 SQLite 索引
if [ ! -f "data/standards.db" ]; then
    echo " [提示] 未找到 data/standards.db，标准检索可能不可用"
    echo "        需要时可运行: $PY scripts/build_index.py"
fi
if [ ! -f "data/units.db" ]; then
    echo " [提示] 未找到 data/units.db，省/市/起草单位筛选可能不可用"
    echo "        需要时可运行: $PY scripts/build_unit_index.py"
fi

echo ""
echo " ========================================"
echo "   ZKBZ 标准PDF下载"
echo "   地址: http://127.0.0.1:5000/"
echo "   请勿关闭本窗口 - 关闭即停止服务"
echo " ========================================"
echo ""

# 启动服务
$PY backend/run.py
