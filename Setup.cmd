@echo off
setlocal
cd /d "%~dp0"
title VisionDB Craft - Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup could not finish. Details are shown above and saved in setup.log.
  pause
  exit /b 1
)
