@echo off
REM Layla launcher (Windows). Runs the server from the source tree.
REM Usage: layla [--help] [--host ADDR] [--port N] [--no-browser] [--reload]
cd /d "%~dp0agent"
python serve.py %*
