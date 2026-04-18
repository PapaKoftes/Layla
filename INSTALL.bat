@echo off
setlocal enabledelayedexpansion
title LAYLA — Installer

cd /d "%~dp0"

cls
echo.
echo  --------------------------------------------------------
echo      ^|^|    ^|  ^|      ^|  ^|^|^|   ^|^|^|    ^|^|
echo      ^|  ^|  ^|^|^|^|  ^|^|  ^|  ^|     ^|  ^|  ^|  ^|  ^|
echo      ^|^|^|   ^|  ^|  ^|  ^|  ^|     ^|^|^|   ^|^|^|
echo      ^|  ^|  ^|  ^|  ^|^|^|^|  ^|  ^|     ^|^|    ^|  ^|
echo      ^|^|^|   ^|  ^|      ^|  ^|^|^|   ^|  ^|    ^|  ^|
echo.
echo            Your personal AI.  No cloud.  No leash.
echo  --------------------------------------------------------
echo.

REM ── Python on PATH ────────────────────────────────────────────────────────
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERROR] Python not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/
    echo          Check "Add Python to PATH" during install.
    pause
    exit /b 1
)
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11+ from https://www.python.org/downloads/
    echo          Check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python %PYVER% found.

for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 (
    echo  [ERROR] Python 3.11+ required.
    pause & exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 11 (
    echo  [ERROR] Python 3.11+ required.
    pause & exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% GEQ 13 (
    echo  [note] Python 3.13+ may run in best-effort or degraded mode if wheels differ.
)
echo.
echo   Starting Layla setup...
echo.

REM ── [1/3] Setting up environment (.venv) ────────────────────────────────────
echo  [1/3] Setting up environment...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Step failed: could not create .venv
        pause
        exit /b 1
    )
    echo       Virtual environment created.
) else (
    echo       .venv already present.
)
echo.

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] Step failed: could not activate .venv
    pause
    exit /b 1
)

REM ── [2/3] Dependencies + model selection ───────────────────────────────────
echo  [2/3] Installing dependencies...
echo       (first run can take several minutes)
echo.
python scripts\setup_layla.py
if errorlevel 1 (
    echo.
    echo  [ERROR] Step failed: setup_layla.py exited with an error.
    echo          Advanced: python scripts\setup_layla.py --help
    pause
    exit /b 1
)
echo.

echo       Installing browser dependencies...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m playwright install chromium
    if errorlevel 1 (
        echo  [ERROR] Step failed: Playwright Chromium install failed.
        pause
        exit /b 1
    )
    echo       Browser automation ready.
) else (
    echo  [ERROR] Step failed: missing .venv\Scripts\python.exe
    pause
    exit /b 1
)
echo.

REM ── [3/3] Launch ───────────────────────────────────────────────────────────
echo  [3/3] Launching Layla...
echo.
python scripts\run_layla.py
set RUNEXIT=!errorlevel!
if !RUNEXIT! neq 0 (
    echo.
    echo  [ERROR] Step failed: run_layla.py exited with code !RUNEXIT!
    pause
    exit /b !RUNEXIT!
)

endlocal
exit /b 0
