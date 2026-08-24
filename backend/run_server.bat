@echo off

chcp 65001 >nul

cd /d "%~dp0"

set "PYTHONUNBUFFERED=1"

set "CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1"

if exist "D:\xuexigongju\tesseract.exe" set "TESSERACT_CMD=D:\xuexigongju\tesseract.exe"

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"

set "PY=%~dp0..\.venv\Scripts\python.exe"

if not exist "%PY%" (

    echo [错误] 未找到 Python 虚拟环境:

    echo   %PY%

    echo 请先运行项目根目录 setup.bat

    pause

    exit /b 1

)

echo 使用 Python: %PY%

echo.

"%PY%" -u app.py

if errorlevel 1 pause

