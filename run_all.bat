@echo off
REM ============================================================
REM  run_all.bat - start the server AND run the full loop.
REM
REM  Opens the server in a SEPARATE window, waits until it's
REM  actually reachable, then runs the loop in THIS window.
REM  When the loop finishes, the server window stays open so you
REM  can run again; close it manually when done.
REM ============================================================

cd /d "%~dp0"

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Launching prototype server in a new window...
start "Prototype Server" cmd /k "cd /d "%~dp0" && call .venv\Scripts\activate.bat && cd prototype && python -m uvicorn main:app --reload --port 8000"

REM ---- Wait for the server to be ready (poll up to ~30s) ----
echo Waiting for server to come up on http://localhost:8000 ...
set /a tries=0
:waitloop
set /a tries+=1
curl -s -o nul http://localhost:8000/api/products
if not errorlevel 1 goto ready
if %tries% geq 30 (
    echo.
    echo  [!] Server did not respond after 30 seconds.
    echo      Check the "Prototype Server" window for errors.
    echo.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo Server is up.

echo.
echo ============================================================
echo   Running full loop
echo ============================================================
echo.

python -m orchestrator.full_loop %*

echo.
echo ============================================================
echo   Loop finished.
echo   The server is still running in its own window.
echo   Close that window when you're done, or run this again.
echo ============================================================
pause >nul
