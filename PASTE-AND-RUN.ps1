# Layla — Quick start (paste and run in any PowerShell window)
# Activates the venv and starts the server, no install needed.
# Run: powershell -ExecutionPolicy Bypass -File ".\PASTE-AND-RUN.ps1"

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $Root) { $Root = (Get-Location).Path }
$AgentDir = Join-Path $Root "agent"
$VenvDir  = Join-Path $Root ".venv"
$py       = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path $VenvDir "bin/python" }
if (-not (Test-Path $py)) {
    Write-Host "Venv not found. Run INSTALL.bat first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Layla..." -ForegroundColor Magenta
Set-Location $AgentDir
& $py -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
