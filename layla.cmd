@echo off
REM Layla launcher (Windows). Runs the server from the source tree.
REM Usage: layla [--help] [--host ADDR] [--port N] [--no-browser] [--reload]
setlocal
REM Prefer the project venv the installer created; fall back to PATH python.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0agent"
"%PY%" serve.py %*
