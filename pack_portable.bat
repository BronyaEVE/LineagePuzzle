@echo off
setlocal

REM ============================================================
REM DataLineage Visualizer - Portable (Green) Package Builder
REM
REM Produces dist-portable\ with embedded Python + all deps + app.
REM Target machine needs NOTHING installed (no Python, no Docker).
REM Just double-click run.bat.
REM
REM Run on dev machine WITH internet. Uses Tsinghua pip mirror
REM (python.org direct download is too slow on CN networks).
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"
set "OUT=%CD%\dist-portable"
set "FE=%CD%\frontend"
set "BE=%CD%\backend"
set "PY_DIR=%OUT%\python"
set "APP_DIR=%OUT%\app"
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "EMBED_URL=https://mirrors.huaweicloud.com/python/3.13.12/python-3.13.12-embed-amd64.zip"

echo.
echo ============================================================
echo   DataLineage Visualizer - Portable Packaging
echo   Embedded Python 3.13.12 + full deps
echo ============================================================
echo.

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%" "%PY_DIR%" "%APP_DIR%" 2>nul
echo [1/6] Output dir: %OUT%

REM --- 1. Build frontend ---
echo.
echo [2/6] Building frontend ...
pushd "%FE%"
call npm run build
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" goto :error_fe
if not exist "%FE%\dist\index.html" goto :error_fe_artifact
echo       Frontend build done

REM --- 2. Download + extract embedded Python ---
echo.
echo [3/6] Downloading embedded Python 3.13.12 (Huawei mirror) ...
powershell -Command "Invoke-WebRequest -Uri '%EMBED_URL%' -OutFile '%OUT%\python.zip' -TimeoutSec 180 -UseBasicParsing"
if not exist "%OUT%\python.zip" goto :error_download
echo       Downloaded: %OUT%\python.zip
powershell -Command "Expand-Archive -Path '%OUT%\python.zip' -DestinationPath '%PY_DIR%' -Force"
del "%OUT%\python.zip"
if not exist "%PY_DIR%\python.exe" goto :error_extract
echo       Embedded Python extracted

REM --- 3. Patch python311._pth: enable site + add site-packages ---
echo.
echo [4/6] Patching python313._pth ...
powershell -Command "$p='%PY_DIR%\python313._pth'; $c=Get-Content $p; if ($c -notcontains 'import site') { Add-Content $p 'import site' }; if ($c -notcontains 'Lib\site-packages') { Add-Content $p 'Lib\site-packages' }; New-Item -ItemType Directory -Force -Path '%PY_DIR%\Lib\site-packages' | Out-Null"
echo       _pth patched (import site + Lib\site-packages)

REM --- 4. Install all deps into embedded site-packages via dev pip ---
echo.
echo [5/6] Installing all deps into embedded Python (this takes a few minutes) ...
REM NOTE: do NOT use --only-binary here (it breaks fastapi resolution with --target).
REM Verified working: plain install with --target into embed site-packages.
python -m pip install -r "%BE%\requirements.txt" --target "%PY_DIR%\Lib\site-packages" --index-url %MIRROR%
set "RC=%errorlevel%"
if not "%RC%"=="0" goto :error_install
echo       Deps installed

REM --- 5. Copy app + frontend ---
echo.
echo [6/6] Copying app and frontend ...
xcopy "%BE%\app" "%APP_DIR%\app\" /e /i /q /y >nul
xcopy "%BE%\tests" "%APP_DIR%\tests\" /e /i /q /y >nul
copy "%BE%\requirements.txt" "%APP_DIR%\" >nul
mkdir "%APP_DIR%\data\scripts" 2>nul
xcopy "%FE%\dist" "%OUT%\frontend\dist\" /e /i /q /y >nul
copy "%CD%\run.bat" "%OUT%\" >nul
copy "%CD%\README_PORTABLE.txt" "%OUT%\" >nul
echo       Files copied

REM --- 6. Smoke test: import critical C extensions via embedded python ---
echo.
echo Validating embedded Python can import C extensions ...
"%PY_DIR%\python.exe" -c "import fastapi,uvicorn,sqlglot,sqlalchemy,pydantic_core._pydantic_core,psycopg2,greenlet,networkx;print('ALL IMPORTS OK')"
set "RC=%errorlevel%"
if not "%RC%"=="0" goto :error_import

REM --- Done ---
echo.
powershell -Command "'Size: {0:N1} MB' -f ((Get-ChildItem '%OUT%' -Recurse | Measure-Object Length -Sum).Sum/1MB)"
echo.
echo ============================================================
echo   Portable packaging complete
echo ============================================================
echo.
echo   Output: %OUT%
echo   Contains: embedded Python 3.13.12 + app + frontend
echo   Target machine: just double-click run.bat (nothing to install)
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

:error_download
echo.
echo [ERROR] Failed to download embedded Python from %EMBED_URL%
exit /b 1

:error_extract
echo.
echo [ERROR] python.exe not found after extraction
exit /b 1

:error_install
echo.
echo [ERROR] pip install into embedded site-packages failed (exit %RC%)
exit /b 1

:error_import
echo.
echo [ERROR] Embedded Python failed to import C extensions (exit %RC%)
echo        The package may not work on target machine
exit /b 1
