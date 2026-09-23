@echo off
rem PVE Seat demo for Windows: double-click this file.
rem First run creates .demo\venv and installs aiohttp + PyYAML (about a minute), then opens the browser.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>nul || (
  echo Python 3.10+ is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause
  exit /b 1
)

if not exist ".demo\venv\Scripts\python.exe" (
  echo Preparing the demo environment in .demo\venv ...
  %PY% -m venv .demo\venv || (pause & exit /b 1)
  ".demo\venv\Scripts\python.exe" -m pip install -q -r requirements-demo.txt || (pause & exit /b 1)
)

echo.
echo PVE Seat demo: http://127.0.0.1:8900  (any password; close this window to stop)
".demo\venv\Scripts\python.exe" demo.py %*
pause
