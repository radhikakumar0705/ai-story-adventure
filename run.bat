@echo off
REM One-click launcher for Windows: creates a venv on first run, installs deps, starts the game.
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - open it and paste your API key after AI_API_KEY= then run this again.
  notepad .env
  pause
  exit /b
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"
python app.py
pause
