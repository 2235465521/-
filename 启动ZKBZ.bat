@echo off
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
call "%~dp0start_zkbz.bat"
pause
