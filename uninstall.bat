@echo off
:: Layla — Uninstaller Launcher
:: Runs the PowerShell uninstaller with appropriate permissions
echo.
echo   Layla Uninstaller
echo   ─────────────────
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
pause
