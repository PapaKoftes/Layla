@echo off
rem Layla installer (Windows) - one command, powered by uv. Fetches Python + every
rem dependency (prebuilt CPU wheels, no compiler, no admin), provisions a model, self-tests.
rem Canonical path; forwards to install\bootstrap.ps1.
powershell -ExecutionPolicy Bypass -File "%~dp0install\bootstrap.ps1" %*
