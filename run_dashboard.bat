@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Double-click install_windows.bat first.
  pause
  exit /b 1
)

echo Starting dashboard on http://localhost:8501
".venv\Scripts\python.exe" -m streamlit run falcon_fx_bot/dashboard/app.py --server.port 8501
pause

