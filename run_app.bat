@echo off
rem Personal Finance - double-click to start.  "run_app.bat demo" opens a separate demo database.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  call "%~dp0setup.bat" || exit /b 1
)

if /i "%~1"=="demo" (
  set "FINANCE_APP_DB=%~dp0demo_data\demo.db"
  ".venv\Scripts\python.exe" scripts\load_example_data.py
)

echo Starting Personal Finance at http://localhost:8501  ^(close this window to stop^)
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 pause
