@echo off
REM ============================================================
REM  run_loop.bat - run ONLY the full demo loop
REM  Assumes the server is ALREADY running (use run_server.bat
REM  in another window first).
REM ============================================================

cd /d "%~dp0"

echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Quick check that the server is reachable before we start.
echo Checking server at http://localhost:8000 ...
curl -s -o nul http://localhost:8000/api/products
if errorlevel 1 (
    echo.
    echo  [!] Server does not seem to be running on port 8000.
    echo      Start it first with run_server.bat in another window,
    echo      then run this again.
    echo.
    pause
    exit /b 1
)
echo Server is up.

echo.
echo ============================================================
echo   Running full loop
echo ============================================================
echo.

python -m orchestrator.full_loop %*

echo.
echo ============================================================
echo   Loop finished. (Press any key to close.)
echo ============================================================
pause >nul
