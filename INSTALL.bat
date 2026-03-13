@echo off
setlocal enabledelayedexpansion
title LAYLA — Installer

cls
echo.
echo  --------------------------------------------------------
echo      ^|^|    ^|  ^|      ^|  ^|^|^|   ^|^|^|    ^|^|
echo      ^|  ^|  ^|^|^|^|  ^|^|  ^|  ^|     ^|  ^|  ^|  ^|  ^|
echo      ^|^|^|   ^|  ^|  ^|  ^|  ^|  ^|     ^|^|^|   ^|^|^|
echo      ^|  ^|  ^|  ^|  ^|^|^|^|  ^|  ^|     ^|^|    ^|  ^|
echo      ^|^|^|   ^|  ^|      ^|  ^|^|^|   ^|  ^|    ^|  ^|
echo.
echo            Your personal AI.  No cloud.  No leash.
echo  --------------------------------------------------------
echo.

REM ── Prerequisites ─────────────────────────────────────────────────────────

echo  [1/6]  Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] Python not found.
    echo.
    echo  Please install Python 3.11 or newer from:
    echo     https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During install, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo      Python %PYVER% found.

REM Check version >= 3.11
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 (
    echo  [!] Python 3.11+ is required. You have %PYVER%.
    pause & exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 11 (
    echo  [!] Python 3.11+ is required. You have %PYVER%.
    pause & exit /b 1
)
echo.

REM ── Virtual environment ────────────────────────────────────────────────────

echo  [2/6]  Creating virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo      .venv already exists, skipping.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo  [!] Failed to create virtual environment.
        pause & exit /b 1
    )
    echo      Done.
)
echo.

REM Activate it
call .venv\Scripts\activate.bat

REM ── Install dependencies ───────────────────────────────────────────────────

echo  [3/6]  Installing dependencies (this may take a few minutes)...
echo         (llama-cpp-python can take 3-5 minutes to compile on first install)
echo.
pip install -q --upgrade pip
pip install -r agent\requirements.txt
if errorlevel 1 (
    echo.
    echo  [!] Dependency install failed.
    echo      Check your internet connection and try again.
    pause & exit /b 1
)
echo.
echo      Dependencies installed.
echo.

REM ── Playwright browser ────────────────────────────────────────────────────

echo  [4/6]  Setting up browser automation (Playwright)...
playwright install chromium >nul 2>&1
if errorlevel 1 (
    echo      [note] Playwright setup had a warning — browser tools may be limited.
) else (
    echo      Browser ready.
)
echo.

REM ── Hardware detection + config wizard ────────────────────────────────────

echo  [5/6]  Detecting your hardware and setting up Layla's config...
echo.
python agent\first_run.py
if errorlevel 1 (
    echo.
    echo  [!] Config setup failed. You can configure manually later.
    echo      Edit: agent\runtime_config.json
    echo      See:  MODELS.md for hardware recommendations.
)
echo.

REM ── Create START.bat if it doesn't exist ──────────────────────────────────

echo  [6/6]  Creating launch shortcut...
if not exist "START.bat" (
    echo @echo off > START.bat
    echo setlocal >> START.bat
    echo title Layla >> START.bat
    echo cd /d "%%~dp0" >> START.bat
    echo call .venv\Scripts\activate.bat >> START.bat
    echo echo Starting Layla... >> START.bat
    echo start "" http://localhost:8000/ui >> START.bat
    echo cd agent >> START.bat
    echo uvicorn main:app --host 127.0.0.1 --port 8000 >> START.bat
)
echo      START.bat ready.
echo.

REM ── Done ──────────────────────────────────────────────────────────────────

echo.
echo  ================================================================
echo   INSTALLATION COMPLETE
echo  ================================================================
echo.
echo   Next step: get a model.
echo.
echo   Open MODELS.md to pick the right model for your hardware.
echo   Put the .gguf file in the  models\  folder.
echo   Then run  agent\first_run.py  again to set the filename,
echo   or just edit  agent\runtime_config.json  directly.
echo.
echo   When you have a model:  double-click  START.bat
echo   Layla will open at:     http://localhost:8000/ui
echo.
echo  ================================================================
echo.
pause
