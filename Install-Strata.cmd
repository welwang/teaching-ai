@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Start Teaching AI once to install Python first.
  pause
  exit /b 1
)
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" install_strata.py >> "logs\strata-install.log" 2>&1
if errorlevel 1 (
  type "logs\strata-install.log"
  echo Installation failed. Run this file again to resume.
  pause
  exit /b 1
)
echo Strata installed. Restart Teaching AI or refresh its model menu.
pause
