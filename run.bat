@echo off
setlocal

REM ============================================================
REM DataLineage Visualizer - Portable Launcher
REM
REM Uses the bundled embedded Python (python\python.exe).
REM Target machine needs NOTHING installed.
REM
REM Usage: double-click this file
REM Browser: http://localhost:8000
REM Stop: Ctrl+C
REM ============================================================

cd /d "%~dp0"
set "PY=%CD%\python\python.exe"
set "PORT=8000"

echo.
echo ============================================================
echo   DataLineage Visualizer
echo ============================================================
echo.

REM --- Check bundled Python exists ---
if not exist "%PY%" (
    echo [ERROR] Bundled Python not found: %PY%
    echo         This doesn't look like a complete portable package.
    pause
    exit /b 1
)

REM --- Start service ---
echo Starting service with bundled Python ...
echo Browser: http://localhost:%PORT%
echo API docs: http://localhost:%PORT%/docs
echo Press Ctrl+C to stop.
echo.

cd /d "%CD%\app"
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%

endlocal
