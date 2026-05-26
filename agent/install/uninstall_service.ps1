# Layla — Remove Windows Service
#
# Stops and removes the LaylaSvc Windows Service.
# Does NOT remove Layla itself, just the service registration.

$ErrorActionPreference = "Stop"

$AgentDir = (Resolve-Path "$PSScriptRoot\..")
$NssmPath = Join-Path $AgentDir "tools\nssm.exe"
$ServiceName = "LaylaSvc"

Write-Host ""
Write-Host "  :: LAYLA - Service Uninstaller" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $NssmPath)) {
    # Try sc.exe as fallback
    $scStatus = sc.exe query $ServiceName 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Stopping service..."
        sc.exe stop $ServiceName 2>$null
        Start-Sleep -Seconds 3
        Write-Host "  Removing service..."
        sc.exe delete $ServiceName 2>$null
        Write-Host "  Service removed." -ForegroundColor Green
    } else {
        Write-Host "  Service '$ServiceName' not found."
    }
    exit 0
}

$status = & $NssmPath status $ServiceName 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Service '$ServiceName' is not installed."
    exit 0
}

Write-Host "  Current status: $status"
Write-Host "  Stopping service..."
& $NssmPath stop $ServiceName 2>$null
Start-Sleep -Seconds 3

Write-Host "  Removing service..."
& $NssmPath remove $ServiceName confirm 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "  Service removed successfully." -ForegroundColor Green
} else {
    Write-Host "  [!] Removal may have failed. Try running as Administrator." -ForegroundColor Yellow
}

Write-Host ""
