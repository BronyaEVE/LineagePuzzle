@echo off
setlocal

REM ============================================================
REM DataLineage Visualizer - Intranet Launcher
REM
REM Prereq: Windows x64 + Python 3.11.5 (3.10/3.12 also work)
REM Usage: double-click this file
REM After start, open http://localhost:8000 in browser
REM ============================================================

cd /d "%~dp0"
set "ROOT=%CD%"
set "PORT=8000"
set "HOST=0.0.0.0"

echo.
echo ============================================================
echo   DataLineage Visualizer - Starting
echo ============================================================
echo.

REM --- 1. Check Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.11+ and add it to PATH.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYFULL=%%v"
for /f "tokens=1,2 delims=." %%a in ("%PYFULL%") do (
    set /a PYMAJOR=%%a
    set /a PYMINOR=%%b
)
echo [1/3] Python version: %PYFULL%

if %PYMAJOR% lss 3 (
    echo [ERROR] Need Python 3.10+, current is %PYFULL%
    pause
    exit /b 1
)
if %PYMAJOR% equ 3 if %PYMINOR% lss 10 (
    echo [ERROR] Need Python 3.10+, current is %PYFULL%
    pause
    exit /b 1
)
if not "%PYFULL%"=="3.11.5" (
    echo [INFO] Recommended 3.11.5, current %PYFULL% also works ^(requires ^>=3.10^)
)

REM --- 2. Install deps (offline, local wheels only, NEVER touch network) ---
echo.
echo [2/3] Checking dependencies...

python -c "import fastapi, sqlglot, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo       Deps not installed, installing from local wheels offline...
    if not exist "%ROOT%\wheels" (
        echo [ERROR] wheels directory not found. Make sure this is a complete offline package.
        pause
        exit /b 1
    )
    REM --no-index: fully offline, do NOT visit PyPI
    REM --find-links: local wheel directory
    python -m pip install ^
        --no-index ^
        --find-links "%ROOT%\wheels" ^
        -r "%ROOT%\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Possible causes:
        echo        1) wheels directory corrupted or files missing
        echo        2) Python version mismatch ^(wheels are cp311, current %PYFULL%^)
        echo        Contact the packager.
        pause
        exit /b 1
    )
    echo       Dependencies installed
) else (
    echo       Dependencies already installed, skipping
)

REM --- 3. Start service ---
echo.
echo [3/3] Starting service at http://%HOST%:%PORT% ...
echo       (press Ctrl+C to stop)
echo.
echo ============================================================
echo   Service starting, please wait...
echo   Browser URL: http://localhost:%PORT%
echo   API docs:    http://localhost:%PORT%/docs
echo ============================================================
echo.

cd /d "%ROOT%\backend"
python -m uvicorn app.main:app --host %HOST% --port %PORT%

endlocal
