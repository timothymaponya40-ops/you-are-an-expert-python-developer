@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Double-click install_windows.bat first.
  pause
  exit /b 1
)

echo Starting Falcon FX webhook server on http://localhost:5000
".venv\Scripts\python.exe" -m falcon_fx_bot.main
pause

