@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run Setup.cmd once before starting this source package.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "launch.py"
