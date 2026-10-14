@echo off
rem Double-click this file to stop everything start.cmd started (scripts\stop.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
echo.
pause
