# Launcher: run start-layla.ps1 from repo root (run this from agent/)
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root "start-layla.ps1"))) {
    Write-Host "Run from repo root: cd .. ; .\start-layla.ps1" -ForegroundColor Yellow
    Write-Host "Or from here: ..\start-layla.ps1" -ForegroundColor Yellow
    exit 1
}
& (Join-Path $Root "start-layla.ps1") @args
