@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ZKBZ标准PDF下载.lnk"
if exist "%LNK%" (
    del /f /q "%LNK%"
    echo  已取消开机自启。
) else (
    echo  未找到开机自启项，无需取消。
)
echo.
pause
endlocal
