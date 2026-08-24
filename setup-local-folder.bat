@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

rem 在本机创建独立开发目录（与服务器目录分开，改完再 push 上传）
set "REPO_URL=https://github.com/Simon-yyy/shipingchoucha.git"
set "BRANCH=fenxi"
set "TARGET_DIR=%~dp0..\chouchafenxi-dev"

echo ========================================
echo   创建本地独立开发目录
echo ========================================
echo.
echo 仓库: %REPO_URL%
echo 分支: %BRANCH%
echo 目标: %TARGET_DIR%
echo.

if exist "%TARGET_DIR%\.git" (
    echo [提示] 目录已存在，正在拉取最新代码...
    pushd "%TARGET_DIR%"
    git fetch origin
    git checkout %BRANCH%
    git pull origin %BRANCH%
    popd
    goto after_clone
)

if exist "%TARGET_DIR%" (
    echo [错误] 目标路径已存在但不是 Git 仓库：
    echo   %TARGET_DIR%
    echo 请手动删除或改名后重试。
    pause
    exit /b 1
)

echo [1/2] 正在克隆...
git clone -b %BRANCH% %REPO_URL% "%TARGET_DIR%"
if errorlevel 1 (
    echo [错误] 克隆失败，请确认已安装 Git 且能访问 GitHub。
    pause
    exit /b 1
)

:after_clone
echo.
echo [2/2] 检查环境...
if not exist "%TARGET_DIR%\.venv\Scripts\python.exe" (
    echo 尚未安装 Python 环境，请在开发目录中运行 setup.bat
) else (
    echo Python 环境已存在
)

echo.
echo ========================================
echo   完成
echo ========================================
echo.
echo 开发目录: %TARGET_DIR%
echo.
echo 日常用法：
echo   1. 进入目录，用 start.bat 启动
echo   2. 本地改代码、验证
echo   3. git add / commit / push 到 fenxi 分支
echo   4. 服务器上 git pull 后重启服务
echo.
set /p OPEN=是否用资源管理器打开开发目录？(Y/N):
if /i "%OPEN%"=="Y" explorer "%TARGET_DIR%"
pause
