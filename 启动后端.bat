@echo off

chcp 65001 >nul

cd /d "%~dp0backend"

echo.

echo ========================================

echo   启动后端 API  -  端口 8080

echo ========================================

echo.

call run_server.bat

