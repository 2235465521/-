@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "ROOT=%~dp0.."
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "VENV_PIP=%ROOT%\.venv\Scripts\pip.exe"
set "CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1"

if not exist "%VENV_PY%" (
    echo 请先运行项目根目录的 setup.bat 创建虚拟环境。
    pause
    exit /b 1
)

echo ========================================
echo  PDF 扫描件 OCR 环境配置
echo ========================================
echo.

echo [1/3] 安装 Python 依赖（含 OCR 可选包）...
"%VENV_PIP%" install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo pip 安装失败，请检查网络或代理后重试。
    pause
    exit /b 1
)
echo.

set "TESS_EXE="
if exist "D:\xuexigongju\tesseract.exe" set "TESS_EXE=D:\xuexigongju\tesseract.exe"
if not defined TESS_EXE if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESS_EXE=C:\Program Files\Tesseract-OCR\tesseract.exe"
where tesseract >nul 2>&1 && for /f "delims=" %%i in ('where tesseract 2^>nul') do if not defined TESS_EXE set "TESS_EXE=%%i"
if defined TESS_EXE (
    echo [2/3] 已检测到 Tesseract: %TESS_EXE%
    goto :set_env
)

echo [2/3] 未检测到 Tesseract（可选，用于部分扫描 PDF）
echo.
echo   下载: https://github.com/UB-Mannheim/tesseract/wiki
echo   安装时勾选 Chinese - Simplified ^(chi_sim^)
echo.
echo   未安装 Tesseract 时仍可使用 RapidOCR / pdfplumber 解析大部分 PDF。
echo.
goto :test_py

:set_env
echo.
echo [3/3] 配置环境变量 TESSERACT_CMD（当前用户）...
setx TESSERACT_CMD "%TESS_EXE%" >nul 2>&1
if errorlevel 1 (
    echo setx 失败，请手动设置 TESSERACT_CMD=%TESS_EXE%
) else (
    echo 已写入 TESSERACT_CMD
)
set "TESSERACT_CMD=%TESS_EXE%"
"%TESS_EXE%" --version
"%TESS_EXE%" --list-langs 2>nul | findstr /i "chi_sim" >nul
if errorlevel 1 (
    echo [警告] 未找到 chi_sim 语言包
) else (
    echo [OK] chi_sim 已安装
)

:test_py
echo.
echo 验证 Python OCR 模块...
"%VENV_PY%" -c "import pytesseract; print('pytesseract OK')" 2>nul || echo pytesseract 未就绪
"%VENV_PY%" -c "from rapidocr_onnxruntime import RapidOCR; print('rapidocr OK')" 2>nul || echo rapidocr 未就绪（Python 3.13 使用 1.2.x）

echo.
echo ========================================
echo  配置完成。运行 start.bat 选 [1] 启动服务
echo ========================================
pause
exit /b 0
