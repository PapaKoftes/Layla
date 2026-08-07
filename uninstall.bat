@echo off
:: Layla - Uninstaller Launcher
:: Runs the PowerShell uninstaller. Pass "purge" to wipe everything with no prompts:
::   uninstall.bat purge
echo.
echo   Layla Uninstaller
echo   -----------------
echo.
if /I "%~1"=="purge" (
    powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" -Purge
) else (
    powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
)
pause
