@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title ZKBZ 标准PDF下载

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
    echo.
    echo  [错误] 未找到 Python 3
    echo  请安装 Python 并勾选 "Add to PATH"
    echo.
    pause
    exit /b 1
)

echo.
echo  正在释放 5000 端口，如有旧进程会先结束…
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo  检查运行依赖…
%PY% -c "import flask, pymysql, dotenv" >nul 2>&1
if errorlevel 1 (
    echo  首次或缺包，正在安装 requirements.txt …
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  [错误] 依赖安装失败，请检查网络或 Python 环境
        pause
        exit /b 1
    )
)

echo  检查 / 准备 MySQL 标准库…
%PY% scripts\setup_mysql.py
set "SETUP_EC=%ERRORLEVEL%"
if not "%SETUP_EC%"=="0" (
    echo.
    echo  [错误] 标准库未就绪（代码 %SETUP_EC%）
    echo  ----------------------------------------
    echo  请确认：
    echo    1. 本机已安装并启动 MySQL
    echo    2. .env 中 MYSQL_USER / MYSQL_PASSWORD 正确
    echo    3. data\db_dump\ 下有 STSC_standard_database.sql.gz
    echo       （若为空请执行: git lfs pull）
    echo  无本机 MySQL 时可用 Docker：
    echo    docker compose up -d mysql
    echo    然后把 .env 设为 MYSQL_PASSWORD=zkbz 再重新运行本脚本
    echo  ----------------------------------------
    pause
    exit /b %SETUP_EC%
)

if not exist "data\product_clusters.json" (
    echo  [提示] 未找到 data\product_clusters.json，高级筛选「产品/品种」扩展可能受限
)

echo.
echo  ========================================
echo    ZKBZ 标准PDF下载
echo    地址: http://127.0.0.1:5000/
echo    数据源: MySQL（项目内备份可自动导入）
echo    启动后会自动打开浏览器
echo    请勿关闭本窗口 - 关闭即停止服务
echo  ========================================
echo.

%PY% backend\run.py
set "EC=%ERRORLEVEL%"

if not "%EC%"=="0" (
    echo.
    echo  [启动失败] 错误代码 %EC%
    echo  请把上面报错信息截图发维护人员
    echo.
    pause
    exit /b %EC%
)

pause
endlocal
