@echo off
setlocal

REM ============================================================
REM DataLineage Visualizer - Offline Package Builder
REM
REM Run on a DEVELOPMENT machine WITH internet access.
REM Produces dist-offline\ folder to copy into the intranet.
REM
REM Target: Windows x64 + Python 3.11.5
REM Usage: double-click this file, or run pack_offline.bat in project root
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"
set "ROOT=%CD%"
set "OUT=%ROOT%\dist-offline"
set "PY_VER=3.11"
set "PLATFORM=win_amd64"

echo.
echo ============================================================
echo   DataLineage Visualizer - Offline Packaging
echo   Target: Python %PY_VER% / %PLATFORM%
echo ============================================================
echo.

REM --- 0. Clean previous output ---
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%" "%OUT%\wheels" 2>nul
echo [1/5] Output dir created: %OUT%

REM --- 1. Build frontend ---
echo.
echo [2/5] Building frontend - npm run build ...
cd /d "%ROOT%\frontend"
call npm run build
if errorlevel 1 goto :error_fe
if not exist "%ROOT%\frontend\dist\index.html" goto :error_fe_artifact
echo       Frontend build done

REM --- 2. Download wheels (KEY: for 3.11, NOT the dev machine 3.13) ---
echo.
echo [3/5] Downloading wheels - target Python %PY_VER% / %PLATFORM% ...
cd /d "%ROOT%\backend"
REM Three critical params ensure cp311 wheels, not dev machine cp313:
REM   --python-version 3.11      target python minor version
REM   --platform win_amd64       target platform
REM   --only-binary :all:        force wheels only, reject .tar.gz - no compiler in intranet
python -m pip download -r requirements.txt -d "%OUT%\wheels" --python-version %PY_VER% --platform %PLATFORM% --only-binary=:all:
if errorlevel 1 goto :error_wheel
echo       Wheel download done

REM --- 3. Copy project files into package ---
echo.
echo [4/5] Copying project files ...
cd /d "%ROOT%"

xcopy "%ROOT%\backend\app" "%OUT%\backend\app\" /e /i /q /y >nul
xcopy "%ROOT%\backend\tests" "%OUT%\backend\tests\" /e /i /q /y >nul
copy "%ROOT%\backend\requirements.txt" "%OUT%\backend\" >nul
copy "%ROOT%\backend\requirements-dev.txt" "%OUT%\backend\" >nul
mkdir "%OUT%\backend\data\scripts" 2>nul

xcopy "%ROOT%\frontend\dist" "%OUT%\frontend\dist\" /e /i /q /y >nul

copy "%ROOT%\start.bat" "%OUT%\" >nul
copy "%ROOT%\README_OFFLINE.txt" "%OUT%\" >nul
copy "%ROOT%\backend\requirements.txt" "%OUT%\" >nul
echo       File copy done

REM --- 4. Validate wheels ---
echo.
echo [5/5] Validating wheels ...
for /f %%n in ('dir /b "%OUT%\wheels\*.whl" ^| find /c /v ""') do set "WHEEL_COUNT=%%n"
echo       Downloaded %WHEEL_COUNT% wheel file(s)

dir /b "%OUT%\wheels\*.whl" | findstr /i "cp313" >nul
if not errorlevel 1 goto :error_cp313

REM --- Done ---
echo.
echo ============================================================
echo   Packaging complete
echo ============================================================
echo.
echo   Output dir: %OUT%
echo.
echo   Structure:
echo     dist-offline\
echo       backend\           backend code
echo       frontend\dist\     frontend static files
echo       wheels\            %WHEEL_COUNT% wheels
echo       requirements.txt
echo       start.bat          intranet launcher
echo       README_OFFLINE.txt
echo.
echo   Next: copy the whole dist-offline folder to intranet, run start.bat
echo.
cd /d "%ROOT%"
goto :eof

REM ============== error handlers ==============
:error_fe
echo.
echo [ERROR] Frontend build failed, check frontend directory
cd /d "%ROOT%"
exit /b 1

:error_fe_artifact
echo.
echo [ERROR] Frontend build artifact missing - frontend\dist\index.html not found
cd /d "%ROOT%"
exit /b 1

:error_wheel
echo.
echo [ERROR] Wheel download failed. Common causes:
echo        A - Some dep has no prebuilt wheel for this Python / platform, lower its version
echo        B - Dev machine is offline
echo        Check the error above, adjust requirements.txt and retry.
cd /d "%ROOT%"
exit /b 1

:error_cp313
echo.
echo [ERROR] cp313 wheels detected - target is 3.11 but found 3.13 wheels
echo        --python-version param may not have taken effect, check pip version
dir /b "%OUT%\wheels\*.whl" | findstr /i "cp313"
exit /b 1
