# Layla — Auto-start setup (ScheduledTask fallback)
#
# If LaylaSvc Windows Service is already installed (via NSSM),
# this script does nothing — the service handles auto-start.
# Otherwise, creates a ScheduledTask to start Layla on user login.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$RepoRoot   = (Resolve-Path "..").Path
$AgentDir   = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$TaskName   = "Jinx Agent Server"
$ServiceName = "LaylaSvc"

Write-Host ""
Write-Host "  :: LAYLA - Auto-Start Setup" -ForegroundColor Cyan
Write-Host "  =============================" -ForegroundColor Cyan
Write-Host ""

# ── Check if NSSM service exists ────────────────────────────────────────────
$NssmPath = Join-Path $AgentDir "tools\nssm.exe"
$serviceExists = $false

if (Test-Path $NssmPath) {
    $status = & $NssmPath status $ServiceName 2>$null
    if ($LASTEXITCODE -eq 0) {
        $serviceExists = $true
    }
} else {
    # Also check via sc.exe
    try {
        $svc = Get-Service -Name $ServiceName -ErrorAction Stop
        $serviceExists = $true
    } catch {}
}

if ($serviceExists) {
    Write-Host "  Windows Service '$ServiceName' is already installed." -ForegroundColor Green
    Write-Host "  No ScheduledTask needed — the service handles auto-start."
    Write-Host ""
    Write-Host "  Service commands:"
    Write-Host "    Start:   nssm start $ServiceName"
    Write-Host "    Stop:    nssm stop $ServiceName"
    Write-Host "    Status:  nssm status $ServiceName"
    Write-Host ""

    # Remove the ScheduledTask if it exists (service supersedes it)
    try {
        $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existingTask) {
            Write-Host "  Removing old ScheduledTask '$TaskName' (service replaces it)..."
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "  Done." -ForegroundColor Green
        }
    } catch {}

    exit 0
}

# ── No service — install ScheduledTask ──────────────────────────────────────

Write-Host "  No Windows Service found. Setting up ScheduledTask instead."
Write-Host ""

if (-not (Test-Path $VenvPython)) {
    Write-Host "  [!] Virtual environment not found at: $VenvPython" -ForegroundColor Red
    Write-Host "      Run install.ps1 first."
    exit 1
}

# Check if task already exists
try {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Host "  ScheduledTask '$TaskName' already exists."
        $choice = Read-Host "  Reinstall? [y/N]"
        if ($choice -ne 'y') {
            Write-Host "  Aborted."
            exit 0
        }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
} catch {}

# Create the ScheduledTask
$action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m uvicorn main:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $AgentDir

$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start Layla AI Assistant on login" | Out-Null

Write-Host "  ScheduledTask '$TaskName' created." -ForegroundColor Green
Write-Host "  Layla will start automatically when you log in."
Write-Host ""
Write-Host "  Tip: For always-on (even before login), install the Windows Service:"
Write-Host "    .\install\install_service.ps1"
Write-Host ""
