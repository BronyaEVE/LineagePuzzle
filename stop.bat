@echo off
REM ============================================================
REM LineagePuzzle - Stop Service
REM
REM Thin wrapper around launcher.pyw stop. Priority: PID file; fallback:
REM port-based lookup. Double-click to run, no interaction needed.
REM ============================================================

cd /d "%~dp0"
set "PYW=%CD%\python\pythonw.exe"
set "LAUNCHER=%CD%\launcher.pyw"

if not exist "%PYW%" (
    echo [ERROR] Bundled Python not found: %PYW%
    pause
    exit /b 1
)

REM pythonw.exe has no window; bat window closes immediately after.
start "" /B "%PYW%" "%LAUNCHER%" stop
exit /b 0
