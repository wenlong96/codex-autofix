@echo off
REM ============================================================
REM  run_dashboard.bat - open the mission-control dashboard
REM  in your default browser, and show the path to the most
REM  recent transcript so you can load it quickly.
REM ============================================================

cd /d "%~dp0"

set "DASH=dashboard\index.html"

if not exist "%DASH%" (
    echo  [!] Dashboard not found at %DASH%
    echo      Check the path or rename your file to dashboard\index.html
    pause
    exit /b 1
)

echo ============================================================
echo   Opening dashboard: %DASH%
echo ============================================================
echo.

REM Find the most recent transcript in personas\reports and print its path.
set "LATEST="
if exist "personas\reports\" (
    for /f "delims=" %%F in ('dir /b /a-d /o-d "personas\reports\full_loop_*.json" 2^>nul') do (
        if not defined LATEST set "LATEST=personas\reports\%%F"
    )
)

if defined LATEST (
    echo Most recent transcript to load:
    echo.
    echo     %CD%\%LATEST%
    echo.
    echo   ^(In the dashboard, click "Choose file..." and paste/navigate
    echo    to the path above, then press Play.^)
) else (
    echo No transcripts found yet in personas\reports\
    echo Run the loop first ^(run_all.bat or run_loop.bat^) to generate one.
)

echo.
start "" "%DASH%"

echo Dashboard opened in your browser.
echo ^(This window can be closed.^)
echo.
pause >nul
