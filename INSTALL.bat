@echo off
rem Layla installer (Windows) - one command, powered by uv. Fetches Python + every
rem dependency (prebuilt CPU wheels, no compiler, no admin), provisions a model, self-tests.
rem Canonical path; forwards to install\bootstrap.ps1.
powershell -ExecutionPolicy Bypass -File "%~dp0install\bootstrap.ps1" %*
rem Keep the window open on failure so a double-click user actually sees the error
rem instead of the window vanishing (the README promises they'll see it).
if errorlevel 1 (
  echo.
  echo ============================================================
  echo   Install did not finish. Scroll up to read the error above.
  echo ============================================================
  pause
)
