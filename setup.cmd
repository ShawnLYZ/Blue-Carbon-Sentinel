@echo off
rem Double-click this file to run the first-time setup (scripts\setup.ps1). It is safe to run again.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
echo.
pause
