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
    echo  Please install Python 3.11 or 3.12 from:
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
    echo  [!] Python 3.11 or 3.12 is required. You have %PYVER%.
    pause & exit /b 1
)
if %PY_MAJOR% GTR 3 (
    echo  [!] Python 3.11 or 3.12 is required. You have %PYVER%.
    pause & exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% GEQ 13 (
    echo  [!] Layla supports Python 3.11 or 3.12 only — not 3.13+. You have %PYVER%.
    echo      Install Python 3.12 from python.org and use it for this venv.
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

REM ── Hardware detection + config wizard + verify ─────────────────────────────

echo  [5/6]  Detecting hardware, setting up config, and verifying...
echo.
python agent\install\run_first_time.py
if errorlevel 1 (
    echo.
    echo  [!] Setup had issues. See above for details.
    echo      Run: python agent\diagnose_startup.py
    echo      See: knowledge\troubleshooting.md
    echo.
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
    echo python -c "import json,pathlib; c=pathlib.Path('agent/runtime_config.json'); cfg=json.loads(c.read_text()) if c.exists() else {}; m=cfg.get('model_filename',''); md=cfg.get('models_dir',''); p=pathlib.Path(md).expanduser()/m if md and m else pathlib.Path('models')/m if m else None; exit(0 if p and p.exists() else 1)" ^>nul 2^>^&1 >> START.bat
    echo if errorlevel 1 ^( >> START.bat
    echo   echo. >> START.bat
    echo   echo   [!] No model found. Run python agent\install\installer_cli.py or see MODELS.md >> START.bat
    echo   echo. >> START.bat
    echo   pause ^& exit /b 1 >> START.bat
    echo ^) >> START.bat
    echo echo. >> START.bat
    echo echo   Layla - http://localhost:8000/ui >> START.bat
    echo echo   Press Ctrl+C to stop. >> START.bat
    echo echo. >> START.bat
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
echo   If the setup wizard didn't download a model:
echo.
echo   • Open MODELS.md to pick the right model for your hardware
echo   • Put the .gguf file in  models\  or  %%USERPROFILE%%\.layla\models\
echo   • Run  python agent\install\installer_cli.py  again to set the filename
echo     (or edit agent\runtime_config.json directly)
echo.
echo   When you have a model:  double-click  START.bat
echo   Layla opens at:        http://localhost:8000/ui
echo.
echo   Repair deps:  python agent\install\installer_cli.py repair
echo   Health check: python agent\install\installer_cli.py doctor
echo   Optional packs: python agent\install\installer_cli.py packs list
echo   Force model URL: python agent\install\installer_cli.py download "https://...file.gguf"
echo.
echo   Linux/macOS users: run  bash install.sh
echo.
echo  ================================================================
echo.
pause
