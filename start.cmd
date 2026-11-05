@echo off
title Blue Carbon Sentinel demo
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo Node.js is not installed. Please install it from https://nodejs.org and double-click start.cmd again.
  echo.
  pause
  exit /b 1
)
if not exist node_modules (
  echo First start: installing what the demo needs. This takes a minute and only happens once...
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo.
    echo The install did not finish. Check the internet connection and try again.
    pause
    exit /b 1
  )
)
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo.
  echo Another program is already using http://localhost:5173 ^(for example another project's website^).
  echo Close that program's window, then double-click start.cmd again.
  echo.
  pause
  exit /b 1
)
echo.
echo Starting the demo at http://localhost:5173 ...
echo Your browser will open by itself. Close this window to stop the demo.
echo.
call npm run dev
pause
