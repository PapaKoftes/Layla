@echo off
setlocal
title Layla
cd /d "%~dp0"

REM Activate venv
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo  [!] Virtual environment not found.
    echo      Run INSTALL.bat first.
    echo.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

REM Check for a model (uses runtime_safety resolution)
python -c "import sys; sys.path.insert(0,'agent'); import runtime_safety; p = runtime_safety.resolve_model_path(runtime_safety.load_config()); sys.exit(0 if p and p.exists() else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  -----------------------------------------------
    echo   No model found.
    echo   Open MODELS.md to choose and download one.
    echo   Then update agent\runtime_config.json with
    echo   the filename and run START.bat again.
    echo  -----------------------------------------------
    echo.
    pause
    exit /b 1
)

echo  Starting Layla...
echo  UI will open at: http://localhost:8000/ui
echo  Press Ctrl+C here to stop.
echo.

REM Open browser after a short delay (background)
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000/ui"

REM Start the server (foreground, visible output)
cd agent
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
