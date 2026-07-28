@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\ZKBZ标准PDF下载.lnk"
set "TARGET=%~dp0打开ZKBZ.bat"

if not exist "%STARTUP%" mkdir "%STARTUP%" 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.WindowStyle=7;" ^
  "$s.Description='开机自动打开 ZKBZ 标准PDF下载';" ^
  "$s.Save()"

if exist "%LNK%" (
    echo.
    echo  已安装开机自启：
    echo  %LNK%
    echo.
    echo  下次登录 Windows 后会自动尝试启动服务并打开网页。
    echo  取消自启请运行：取消开机自启.bat
    echo.
) else (
    echo  [失败] 未能创建快捷方式，请以当前用户权限重试。
)
pause
endlocal
