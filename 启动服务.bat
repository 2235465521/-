@echo off
cd /d "%~dp0"
call "%~dp0start.bat" start
if errorlevel 1 pause
