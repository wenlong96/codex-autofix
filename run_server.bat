@echo off
REM ============================================================
REM  run_server.bat - start ONLY the prototype server
REM  Leave this window open while you run the loop separately.
REM ============================================================

cd /d "%~dp0"

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo ============================================================
echo   Starting prototype server on http://localhost:8000
echo   (Ctrl+C to stop)
echo ============================================================
echo.

cd prototype
python -m uvicorn main:app --reload --port 8000
