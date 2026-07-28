@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "DESK=%USERPROFILE%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\OneDrive\Desktop"
set "LNK=%DESK%\打开ZKBZ.lnk"
set "TARGET=%~dp0打开ZKBZ.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory='%~dp0.';" ^
  "$s.Description='启动并打开 ZKBZ 标准PDF下载';" ^
  "$s.Save()"

if exist "%LNK%" (
    echo.
    echo  已在桌面创建快捷方式：打开ZKBZ
    echo  以后双击桌面图标即可，无需先打开 Cursor。
    echo.
) else (
    echo  [失败] 未能创建桌面快捷方式。
)
pause
endlocal
