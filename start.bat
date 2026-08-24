@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"
set "CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1"

if exist "D:\xuexigongju\tesseract.exe" (
    set "TESSERACT_CMD=D:\xuexigongju\tesseract.exe"
) else if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    set "TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"
)

if /i "%~1"=="start" goto start_all
if /i "%~1"=="stop" goto stop_services
if /i "%~1"=="backend" goto start_backend
if /i "%~1"=="frontend" goto start_frontend

:menu
cls
echo ========================================
echo   食品安全监督抽检数据统计
echo ========================================
echo.
call :status_line
echo.
echo   1. 启动服务 - 后端 + 前端
echo   2. 仅启动后端 API  :8080
echo   3. 仅启动前端页面  :5173
echo   4. 停止服务 - 释放 8080 / 5173
echo   5. 安装/修复环境依赖
echo   6. 配置 PDF OCR - 可选
echo   0. 退出
echo.
set "CHOICE="
set /p CHOICE=请选择:
if "%CHOICE%"=="1" goto start_all
if "%CHOICE%"=="2" goto start_backend
if "%CHOICE%"=="3" goto start_frontend
if "%CHOICE%"=="4" goto stop_services
if "%CHOICE%"=="5" goto run_setup
if "%CHOICE%"=="6" goto run_ocr_setup
if "%CHOICE%"=="0" exit /b 0
echo 无效选项，请重试。
call :sleep 2
goto menu

:status_line
set "BE=未运行"
set "FE=未运行"
call :port_listening 8080
if not errorlevel 1 set "BE=运行中"
call :port_listening 5173
if not errorlevel 1 set "FE=运行中"
if not exist "%VENV_PY%" (
    echo   环境: 未安装 - 请先选 5
) else (
    set "PYTAG="
    for /f "delims=" %%v in ('"%VENV_PY%" -c "import sys; print(sys.version.split()[0])" 2^>nul') do set "PYTAG=%%v"
    if not defined PYTAG set "PYTAG=未知版本"
    echo   环境: Python !PYTAG! - .venv
)
echo   后端 8080: !BE!    前端 5173: !FE!
exit /b 0

:ensure_env
if not exist "%VENV_PY%" (
    echo.
    echo [提示] 尚未安装环境，正在打开安装向导...
    call "%~dp0setup.bat"
)
if not exist "%VENV_PY%" (
    echo [错误] 环境仍未就绪，无法启动。
    pause
    if /i not "%~1"=="start" goto menu
    exit /b 1
)
if not exist "%FRONTEND_DIR%\node_modules" (
    echo [提示] 前端依赖缺失，请先在菜单选 5 完成安装。
    pause
    if /i not "%~1"=="start" goto menu
    exit /b 1
)
exit /b 0

:sleep
set /a "_SLEEP_N=%~1+1"
ping 127.0.0.1 -n !_SLEEP_N! >nul 2>&1
exit /b 0

:port_listening
netstat -ano | findstr /C:":%1 " | findstr "LISTENING" >nul 2>&1
exit /b %errorlevel%

:kill_port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%1 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
exit /b 0

:wait_port
set "WAIT_PORT=%~1"
set "WAIT_MAX=%~2"
set /a WP_N=0
:wait_port_loop
call :sleep 1
set /a WP_N+=1
call :port_listening %WAIT_PORT%
if not errorlevel 1 exit /b 0
if !WP_N! geq %WAIT_MAX% exit /b 1
goto wait_port_loop

:wait_backend_http
set "WAIT_HTTP_MAX=%~1"
set /a WAIT_HTTP=0
:wait_backend_http_loop
call :sleep 1
set /a WAIT_HTTP+=1
"%VENV_PY%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" >nul 2>&1
if not errorlevel 1 exit /b 0
if !WAIT_HTTP! geq %WAIT_HTTP_MAX% exit /b 1
goto wait_backend_http_loop

:stop_services
echo.
echo 正在停止 8080 / 5173 ...
call :kill_port 8080
call :kill_port 5173
echo 已发送停止指令。
call :sleep 2
if /i "%~1"=="stop" exit /b 0
goto menu

:run_setup
call "%~dp0setup.bat"
goto menu

:run_ocr_setup
call "%BACKEND_DIR%\setup_ocr.bat"
goto menu

:launch_backend
start "food-backend" cmd /k call "%~dp0启动后端.bat"
exit /b 0

:launch_frontend
start "food-frontend" cmd /k call "%~dp0启动前端.bat"
exit /b 0

:start_backend
call :ensure_env
call :port_listening 8080
if not errorlevel 1 (
    echo 后端已在运行。
    pause
    goto menu
)
echo.
echo 启动后端...
call :launch_backend
echo 后端窗口已打开。
pause
goto menu

:start_frontend
if not exist "%FRONTEND_DIR%\node_modules" (
    echo 请先运行菜单 5 安装前端依赖。
    pause
    goto menu
)
call :port_listening 5173
if not errorlevel 1 (
    echo 前端已在运行。
    pause
    goto menu
)
echo.
echo 启动前端...
call :launch_frontend
echo 前端窗口已打开。
pause
goto menu

:start_all
call :ensure_env start
if errorlevel 1 exit /b 1
echo.
echo 正在关闭旧服务...
call :kill_port 8080
call :kill_port 5173

echo 启动后端 Flask :8080 ...
call :launch_backend

echo 等待后端端口 - 最多 30 秒 ...
call :wait_port 8080 30
if errorlevel 1 (
    echo [错误] 8080 未监听，请查看 food-backend 窗口。
    pause
    if /i not "%~1"=="start" goto menu
    exit /b 1
)

echo 等待 API 健康检查 - 最多 15 秒 ...
call :wait_backend_http 15
if errorlevel 1 (
    echo [错误] 后端 API 无响应，请查看 food-backend 窗口。
    pause
    if /i not "%~1"=="start" goto menu
    exit /b 1
)
echo 后端端口已就绪（pandas 仍在后台加载，页面会自动刷新数据）。

echo 启动前端 Vue :5173 ...
call :launch_frontend

echo 等待前端 5173 ...
call :wait_port 5173 60
if errorlevel 1 (
    echo [警告] 等待前端超时，请查看 food-frontend 窗口。
    pause
    if /i not "%~1"=="start" goto menu
    exit /b 1
)

echo.
echo 服务已就绪:
echo   前端  http://127.0.0.1:5173
echo   后端  http://127.0.0.1:8080
echo.
start "" "http://127.0.0.1:5173/"
echo 已在浏览器打开前端。
echo 请保持 food-backend 与 food-frontend 两个窗口不要关闭。
echo.
if /i "%~1"=="start" exit /b 0
pause
goto menu
