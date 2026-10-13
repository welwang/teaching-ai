@echo off
setlocal
title Curriculum AI - Setup and Launch
pushd "%~dp0"
if errorlevel 1 goto folder_failed

echo [1/2] Checking and installing the application environment...
echo Missing Python and packages will be installed automatically.
echo The first installation requires an internet connection.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" -NoLaunch
if errorlevel 1 goto failed

echo [2/2] Starting Curriculum AI...
set "PYTHONUTF8=1"
"%~dp0.venv\Scripts\python.exe" "%~dp0launch_v2.py"
if errorlevel 1 goto failed

popd
endlocal
exit /b 0

:failed
set "setup_exit=%errorlevel%"
echo.
echo Setup or startup failed. Review the error above.
echo If Windows Application Control blocked Python, contact your device administrator.
echo After resolving the error, run this file again to retry.
pause
popd
exit /b %setup_exit%

:folder_failed
echo Cannot open the application folder: %~dp0
pause
exit /b 1
