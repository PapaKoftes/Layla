@echo off
setlocal
title Layla - Test then Server (Ctrl+C to stop)
cd /d "%~dp0"

REM Activate venv
if not exist ".venv\Scripts\activate.bat" (
    echo [!] Virtual environment not found. Run INSTALL.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

echo.
echo  === Running full test suite ===
cd agent
python -m pytest tests/ -v -m "not slow" --tb=short
set TEST_EXIT=%ERRORLEVEL%
cd ..
if not %TEST_EXIT%==0 (
    echo.
    echo  Tests failed. Fix before starting server.
    pause
    exit /b %TEST_EXIT%
)
echo.
echo  === Tests passed. Starting Layla ===
echo  UI: http://localhost:8000/ui
echo  >>> Press Ctrl+C in this window to stop the server <<<
echo.

start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000/ui"
cd agent
uvicorn main:app --host 127.0.0.1 --port 8000
