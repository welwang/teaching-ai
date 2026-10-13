@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto.ps1" %*
pause
