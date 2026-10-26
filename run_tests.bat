@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "%~dp0setup.bat" || exit /b 1
".venv\Scripts\python.exe" -m pytest -q
pause
