# Layla installer (Windows) — one command, powered by uv.
#
# uv fetches a standalone Python and installs every dependency from prebuilt CPU wheels
# (no compiler, no system Python, no admin), then provisions a model and self-tests.
# This is the canonical install path; it forwards to install\bootstrap.ps1.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
param([Parameter(ValueFromRemainingArguments = $true)]$Rest)
$ErrorActionPreference = "Stop"
$target = Join-Path $PSScriptRoot "install\bootstrap.ps1"
if (-not (Test-Path $target)) { throw "install\bootstrap.ps1 not found next to this shim." }
& $target @Rest
