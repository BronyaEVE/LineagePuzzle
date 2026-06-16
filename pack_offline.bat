@echo off
setlocal

REM ============================================================
REM DataLineage Visualizer - Offline Package Builder
REM Run on dev machine WITH internet. Produces dist-offline\ for intranet.
REM Target: Windows x64 + Python 3.11.x
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"
set "OUT=%CD%\dist-offline"
set "FE=%CD%\frontend"
set "BE=%CD%\backend"
set "PY_VER=3.11"
set "PLATFORM=win_amd64"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

echo.
echo ============================================================
echo   DataLineage Visualizer - Offline Packaging
echo   Target: Python %PY_VER% / %PLATFORM%
echo ============================================================
echo.

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%" "%OUT%\wheels" 2>nul
echo [1/5] Output dir: %OUT%

REM --- 1. Build frontend ---
echo.
echo [2/5] Building frontend ...
pushd "%FE%"
call npm run build
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" goto :error_fe
if not exist "%FE%\dist\index.html" goto :error_fe_artifact
echo       Frontend build done

REM --- 2. Download wheels ---
echo.
echo [3/5] Downloading wheels via mirror ...
pushd "%BE%"
python -m pip download -r requirements.txt -d "%OUT%\wheels" --python-version %PY_VER% --platform %PLATFORM% --only-binary=:all: --index-url %PIP_INDEX%
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" goto :error_wheel
echo       Wheel download done

REM --- 3. Copy files ---
echo.
echo [4/5] Copying project files ...
xcopy "%BE%\app" "%OUT%\backend\app\" /e /i /q /y >nul
xcopy "%BE%\tests" "%OUT%\backend\tests\" /e /i /q /y >nul
copy "%BE%\requirements.txt" "%OUT%\backend\" >nul
copy "%BE%\requirements-dev.txt" "%OUT%\backend\" >nul
mkdir "%OUT%\backend\data\scripts" 2>nul
xcopy "%FE%\dist" "%OUT%\frontend\dist\" /e /i /q /y >nul
copy "%CD%\start.bat" "%OUT%\" >nul
copy "%CD%\README_OFFLINE.txt" "%OUT%\" >nul
copy "%BE%\requirements.txt" "%OUT%\" >nul
echo       File copy done

REM --- 4. Validate ---
echo.
echo [5/5] Validating wheels ...
set /a WC=0
for /f %%n in ('dir /b "%OUT%\wheels\*.whl" ^| find /c /v ""') do set "WC=%%n"
echo       Downloaded %WC% wheel file(s)
dir /b "%OUT%\wheels\*.whl" | findstr /i "cp313" >nul
if not errorlevel 1 goto :error_cp313

echo.
echo ============================================================
echo   Packaging complete
echo ============================================================
echo.
echo   Output: %OUT%
echo   Wheels: %WC% files
echo   Next: copy dist-offline\ to intranet, run start.bat
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

:error_wheel
echo.
echo [ERROR] Wheel download failed. Check network or requirements.txt versions.
exit /b 1

:error_cp313
echo.
echo [ERROR] cp313 wheels detected - target is 3.11
dir /b "%OUT%\wheels\*.whl" | findstr /i "cp313"
exit /b 1
