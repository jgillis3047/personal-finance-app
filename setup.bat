@echo off
setlocal
cd /d "%~dp0"

rem ---- find Python 3.12+ ----
set "PY="
for %%V in (3.13 3.12 3.14) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3.12 or newer was not found.
  echo Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^), then run this again.
  echo.
  pause
  exit /b 1
)
echo Using %PY%

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv || goto :fail
)
echo Installing packages ^(first run takes a few minutes^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
".venv\Scripts\python.exe" scripts\init_db.py || goto :fail
echo.
echo Setup complete.
exit /b 0

:fail
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
