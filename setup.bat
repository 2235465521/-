@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "VENV_PIP=%ROOT%.venv\Scripts\pip.exe"
set "CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1"

echo ========================================
echo  食品安全监督抽检统计 - 环境安装/修复
echo ========================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%v in ('py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "PY_VER=%%v"
    set "PY_LAUNCHER=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [错误] 未找到 Python。请安装 Python 3.10~3.13 并勾选 Add to PATH。
        pause
        exit /b 1
    )
    for /f "delims=" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "PY_VER=%%v"
    set "PY_LAUNCHER=python"
)

echo 检测到 Python %PY_VER%

if not exist "%VENV_PY%" (
    echo.
    echo [1/4] 创建虚拟环境 .venv ...
    %PY_LAUNCHER% -m venv "%ROOT%.venv"
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
) else (
    echo.
    echo [1/4] 虚拟环境已存在，跳过创建
)

echo.
echo [2/4] 升级 pip 并安装后端依赖 ...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PIP%" install -r "%ROOT%backend\requirements.txt"
if errorlevel 1 (
    echo.
    echo [错误] pip 安装失败。请检查网络/代理后重试 setup.bat
    pause
    exit /b 1
)

echo.
echo [3/4] 检查前端依赖 ...
where npm >nul 2>&1
if errorlevel 1 (
    echo [警告] 未找到 npm，请安装 Node.js 后重新运行 setup.bat
) else if not exist "%ROOT%frontend\node_modules" (
    echo 正在 npm install ...
    pushd "%ROOT%frontend"
    call npm install
    if errorlevel 1 (
        popd
        echo [错误] npm install 失败
        pause
        exit /b 1
    )
    popd
) else (
    echo node_modules 已存在，跳过 npm install
)

echo.
echo [4/4] 验证关键模块 ...
"%VENV_PY%" -c "import flask,pandas,openpyxl,xlrd,pdfplumber; print('核心依赖 OK')"
if errorlevel 1 (
    echo [错误] 核心模块导入失败
    pause
    exit /b 1
)

"%VENV_PY%" -c "import rapidocr_onnxruntime; print('rapidocr OK', rapidocr_onnxruntime.__version__ if hasattr(rapidocr_onnxruntime,'__version__') else '')" 2>nul
if errorlevel 1 (
    echo [提示] rapidocr 未安装或不可用，PDF 扫描件 OCR 将降级为文本提取
) else (
    echo rapidocr 可用
)

echo.
echo ========================================
echo  环境就绪。请运行 start.bat 启动服务
echo ========================================
pause
exit /b 0
