@echo off
REM LAUNCHER.bat - double-click this on Windows to start Arrival.
REM
REM Works identically on x86-64 and ARM (Snapdragon / Surface) Windows.
REM Everything it installs lives inside this folder, so deleting the folder
REM removes every trace. No administrator rights, no system Python, no Node.
REM
REM macOS users: double-click LAUNCHER.command instead.

setlocal enabledelayedexpansion
title Arrival - honest A&E waits for Hong Kong

set "ROOT=%~dp0"
set "UV_DIR=%ROOT%.uv"
set "UV_BIN=%UV_DIR%\uv.exe"
set "PORT=8094"

REM Keep every byte uv writes inside this folder rather than %LOCALAPPDATA%.
set "UV_CACHE_DIR=%ROOT%.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%ROOT%.uv-python"
set "UV_PYTHON_CACHE_DIR=%ROOT%.uv-cache\python"
set "UV_PYTHON_BIN_DIR=%ROOT%.uv-python\bin"
set "UV_TOOL_DIR=%ROOT%.uv-tools"
set "UV_TOOL_BIN_DIR=%ROOT%.uv-tools\bin"

cd /d "%ROOT%"

echo.
echo   Arrival - honest A^&E waits for Hong Kong
echo   Windows %PROCESSOR_ARCHITECTURE%
echo.

REM -- 1. Find uv, or install it into this folder ------------------------
REM uv publishes native builds for both x86-64 and ARM64 Windows, and the
REM installer picks the right one automatically.
set "UV="
if exist "%UV_BIN%" (
    set "UV=%UV_BIN%"
) else (
    where uv >nul 2>nul
    if not errorlevel 1 set "UV=uv"
)

if not defined UV (
    echo   First run - setting up. Needs internet; only happens once.
    echo.
    echo   Step 1 of 3: downloading the setup tool...
    powershell -ExecutionPolicy ByPass -c "$env:UV_UNMANAGED_INSTALL='%UV_DIR%'; irm https://astral.sh/uv/install.ps1 | iex" >nul 2>nul
    if not exist "%UV_BIN%" goto :no_uv
    set "UV=%UV_BIN%"
)

if not exist "%ROOT%engine\pyproject.toml" goto :no_engine
cd /d "%ROOT%engine"

REM -- 2. Python + Flask -------------------------------------------------
REM Flask is pure Python, so there is no compiled wheel that has to match the
REM CPU. The same command works on x86-64 and ARM64 alike.
echo   Step 2 of 3: installing Python and Flask...
"!UV!" sync --quiet
if not errorlevel 1 goto :synced
echo   That did not work. Rebuilding from scratch...
rmdir /s /q ".venv" >nul 2>nul
"!UV!" sync --quiet
if errorlevel 1 goto :sync_failed
:synced

REM -- 3. Data present? --------------------------------------------------
if exist "%ROOT%data\ae_corpus.json" goto :havedata
if exist "%ROOT%data\ae_corpus.json.gz" goto :havedata
goto :no_data
:havedata

REM -- 3b. Built page present? ----------------------------------------------
REM Without this the server starts happily and serves a blank window, which is
REM the worst failure mode: it looks like the app works and simply has nothing
REM to say.
if not exist "%ROOT%frontend\dist\index.html" goto :no_page

echo   Step 3 of 3: starting up...
echo.
echo   Opening http://localhost:%PORT%
echo   Leave this window open. Closing it stops Arrival.
echo.

REM Open the browser shortly after the server begins listening.
start "" /b powershell -ExecutionPolicy ByPass -c "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:%PORT%'; break}catch{Start-Sleep -Seconds 1}}" >nul 2>nul

"!UV!" run python server.py %PORT%
if errorlevel 1 goto :crashed
exit /b 0

:no_uv
echo.
echo   Could not download the setup tool.
echo.
echo   Check your internet connection and try again. If you are on a
echo   university or company network that blocks downloads, try a
echo   different network.
echo.
pause
exit /b 1

:no_engine
echo.
echo   The 'engine' folder is missing.
echo.
echo   Extract the whole download before running this, not just the
echo   launcher. Right-click the .zip and choose "Extract All".
echo.
pause
exit /b 1

:no_data
echo.
echo   The historical data file is missing from the 'data' folder.
echo   Re-extract the download.
echo.
pause
exit /b 1

:no_page
echo.
echo   The built page is missing from 'frontend\dist'.
echo   Re-extract the download, or run "npm install" then "npm run build"
echo   inside the frontend folder.
echo.
pause
exit /b 1

:sync_failed
echo.
echo   Could not install Python or Flask.
echo   Check your internet connection and try again.
echo.
pause
exit /b 1

:crashed
echo.
echo   Arrival closed with an error.
echo.
pause
exit /b 1
