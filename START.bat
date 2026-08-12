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
    echo   Download one now ^(hardware-matched, no editing^):
    echo.
    echo       .venv\Scripts\python.exe agent\install\provision_model.py
    echo.
    echo   Then run START.bat again. ^(To pick manually instead,
    echo   see MODELS.md and set the filename in
    echo   agent\runtime_config.json.^)
    echo  -----------------------------------------------
    echo.
    pause
    exit /b 1
)

echo  Starting Layla...
echo  Press Ctrl+C here to stop.
echo.

REM Start via serve.py: it checks the port first so Layla never collides with
REM another program on :8000 (auto-relocates to a free port, or opens the
REM already-running instance), and opens the browser at the correct port.
cd agent
python serve.py
set "LAYLA_RC=%ERRORLEVEL%"

REM If Layla exited with an error, KEEP THIS WINDOW OPEN so the message above is
REM readable. A double-click launch must never vanish on a crash. A clean stop
REM (Ctrl+C -> exit code 0) closes normally.
if not "%LAYLA_RC%"=="0" (
    echo.
    echo  ------------------------------------------------------------
    echo   [!] Layla stopped with an error ^(exit code %LAYLA_RC%^).
    echo       The details are in the text above this line.
    echo.
    echo   Common causes and fixes:
    echo     - Port 8000 is busy ........... close the other program, or
    echo                                     set "port" in agent\runtime_config.json
    echo     - A dependency failed to load . re-run INSTALL.bat
    echo     - The model is missing/broken . re-run INSTALL.bat, or see MODELS.md
    echo  ------------------------------------------------------------
    echo.
    pause
)
endlocal
