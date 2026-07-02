@echo off
rem Layla - DEPRECATED installer shim. The old batch installer needed a C++ toolchain and a
rem bare `python` (often 3.14, unsupported). Forwarding to the compiler-free installer.
echo.
echo   [deprecated] This installer needed a C++ toolchain. Using the compiler-free installer instead:
echo     install\fresh_install.ps1
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0install\fresh_install.ps1" %*
