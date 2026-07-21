@echo off
REM ============================================================
REM LineagePuzzle - Portable Launcher
REM
REM Thin wrapper around launcher.pyw (run via pythonw.exe, no window).
REM Double-click to start: uvicorn runs in background, browser opens
REM automatically. If already running, just reopens the browser.
REM
REM Stop: double-click stop.bat
REM ============================================================

cd /d "%~dp0"
set "PYW=%CD%\python\pythonw.exe"
set "LAUNCHER=%CD%\launcher.pyw"

if not exist "%PYW%" (
    echo [ERROR] Bundled Python not found: %PYW%
    echo         This doesn't look like a complete portable package.
    pause
    exit /b 1
)

REM pythonw.exe has no console window; the bat window closes immediately after.
REM launcher.pyw handles: port-in-use check, uvicorn launch, PID file, browser open.
start "" /B "%PYW%" "%LAUNCHER%" start
exit /b 0
