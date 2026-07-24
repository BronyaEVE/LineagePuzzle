@echo off
setlocal

REM ============================================================
REM LineagePuzzle - Desktop (Window) Package Builder
REM
REM Produces dist\LineagePuzzle\ via PyInstaller (onedir).
REM Target machine double-clicks LineagePuzzle.exe and gets a
REM native desktop window (no browser, no terminal). Closing the
REM window exits cleanly — no leftover uvicorn process.
REM
REM Prereq (dev machine): Python 3.13 with deps installed
REM   (pip install -r backend\requirements.txt + pywebview + pyinstaller)
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"
set "VERSION=2.1.0"
set "DIST=%CD%\dist"
set "APPDIR=%DIST%\LineagePuzzle"
set "ZIP=%CD%\LineagePuzzle-Desktop-v%VERSION%-portable.zip"
set "FE=%CD%\frontend"

echo.
echo ============================================================
echo   LineagePuzzle v%VERSION% - Desktop Packaging
echo   PyInstaller onedir (native window via PyWebView)
echo ============================================================
echo.

if exist "%APPDIR%" rmdir /s /q "%APPDIR%"
if exist "%ZIP%" del "%ZIP%"

REM --- 1. Build frontend ---
echo [1/4] Building frontend ...
pushd "%FE%"
call npm run build
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" goto :error_fe
if not exist "%FE%\dist\index.html" goto :error_fe_artifact
echo       Frontend build done

REM --- 2. PyInstaller pack ---
echo.
echo [2/4] Running PyInstaller (this takes a few minutes, sqlglot[c] has 200+ .pyd) ...
pyinstaller LineagePuzzle.spec --noconfirm --log-level WARN
set "RC=%errorlevel%"
if not "%RC%"=="0" goto :error_pyinstaller
if not exist "%APPDIR%\LineagePuzzle.exe" goto :error_pyinstaller
echo       PyInstaller done: %APPDIR%\LineagePuzzle.exe

REM --- 3. Create data dir placeholder (store.py writes user data here at runtime) ---
mkdir "%APPDIR%\backend\data\scripts" 2>nul
echo       Created backend\data\ (runtime user data)

REM --- 4. Compress to zip ---
echo.
echo [4/4] Compressing to %ZIP% (this takes a few minutes) ...
powershell -Command "Compress-Archive -Path '%APPDIR%\*' -DestinationPath '%ZIP%' -CompressionLevel Optimal"
if not exist "%ZIP%" goto :error_zip
echo       Zip created

REM --- Done ---
echo.
powershell -Command "'Uncompressed: {0:N1} MB' -f ((Get-ChildItem '%APPDIR%' -Recurse | Measure-Object Length -Sum).Sum/1MB)"
powershell -Command "'Zip size: {0:N1} MB' -f ((Get-Item '%ZIP%').Length/1MB)"
echo.
echo ============================================================
echo   Desktop packaging complete
echo ============================================================
echo.
echo   Output dir: %APPDIR%
echo   Zip:        %ZIP%
echo   Version:    v%VERSION%
echo   Launch:     extract zip, double-click LineagePuzzle.exe
echo   Target machine: Win10 1803+ / Win11 (WebView2 runtime required, usually preinstalled)
echo.
goto :eof

:error_fe
echo.
echo [ERROR] Frontend build failed
exit /b 1

:error_fe_artifact
echo.
echo [ERROR] frontend\dist\index.html missing after build
exit /b 1

:error_pyinstaller
echo.
echo [ERROR] PyInstaller failed (exit %RC%)
exit /b 1

:error_zip
echo.
echo [ERROR] Failed to create zip at %ZIP%
echo        %APPDIR% directory is still valid; you can launch it directly
exit /b 1
