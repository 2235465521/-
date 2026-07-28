@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title 打开ZKBZ

set "URL=http://127.0.0.1:5000/"

rem 已在监听则直接打开浏览器
netstat -ano 2>nul | findstr ":5000" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo  服务已在运行，正在打开浏览器...
    start "" "%URL%"
    exit /b 0
)

echo  服务未启动，正在后台拉起 ZKBZ...
rem 使用 "%~dp0." 避免路径末尾 \ 吃掉引号（否则会出现 'KBZ' 不是内部或外部命令）
start "ZKBZ" /D "%~dp0." cmd /k call "%~dp0start_zkbz.bat"

rem 等待端口就绪（最多约 90 秒）
set /a n=0
:wait_loop
timeout /t 2 /nobreak >nul
netstat -ano 2>nul | findstr ":5000" | findstr "LISTENING" >nul
if not errorlevel 1 goto ready
set /a n+=1
if %n% GEQ 45 (
    echo.
    echo  [超时] 服务未能在预期时间内启动。
    echo  请查看弹出的黑色窗口中的报错，或手动运行 启动ZKBZ.bat
    echo.
    pause
    exit /b 1
)
goto wait_loop

:ready
echo  服务已就绪，正在打开浏览器...
start "" "%URL%"
endlocal
exit /b 0
