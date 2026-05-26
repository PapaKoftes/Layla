# Layla — Install as Windows Service (via NSSM)
#
# Registers Layla as a Windows Service that:
#   - Starts automatically at boot (before user login)
#   - Restarts on crash (10-second delay)
#   - Runs at Below Normal priority (user apps get priority)
#   - Logs to agent/logs/service.log
#
# Requires: .venv already created (run install.ps1 first)
# NSSM: bundled in tools/nssm.exe (MIT license, ~400KB)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..")
$AgentDir = Join-Path $RepoRoot "agent"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$NssmPath = Join-Path $AgentDir "tools\nssm.exe"
$LogDir = Join-Path $AgentDir "logs"
$ServiceName = "LaylaSvc"

Write-Host ""
Write-Host "  :: LAYLA - Service Installer" -ForegroundColor Cyan
Write-Host "  =============================" -ForegroundColor Cyan
Write-Host ""

# ── [1] Pre-checks ──────────────────────────────────────────────────────────

if (-not (Test-Path $VenvPython)) {
    Write-Host "  [!] Virtual environment not found at: $VenvPython" -ForegroundColor Red
    Write-Host "      Run install.ps1 first to create the environment."
    exit 1
}

if (-not (Test-Path $NssmPath)) {
    Write-Host "  NSSM not found — downloading automatically..." -ForegroundColor Yellow
    $ToolsDir = Join-Path $AgentDir "tools"
    if (-not (Test-Path $ToolsDir)) {
        New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
    }
    $NssmZip = Join-Path $ToolsDir "nssm.zip"
    $NssmTmp = Join-Path $ToolsDir "nssm-tmp"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip -UseBasicParsing
        Expand-Archive -Path $NssmZip -DestinationPath $NssmTmp -Force
        $Arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
        Copy-Item (Join-Path $NssmTmp "nssm-2.24\$Arch\nssm.exe") $NssmPath -Force
        # Cleanup temp files
        Remove-Item $NssmZip -Force -ErrorAction SilentlyContinue
        Remove-Item $NssmTmp -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  NSSM downloaded and installed to: $NssmPath" -ForegroundColor Green
    } catch {
        Write-Host "  [!] Failed to download NSSM automatically." -ForegroundColor Red
        Write-Host "      Error: $_"
        Write-Host ""
        Write-Host "  Manual download:"
        Write-Host "    1. Download from https://nssm.cc/release/nssm-2.24.zip"
        Write-Host "    2. Extract nssm-2.24\win64\nssm.exe to $NssmPath"
        Write-Host ""
        exit 1
    }
}

# ── [2] Check for existing service ──────────────────────────────────────────

$existing = & $NssmPath status $ServiceName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Service '$ServiceName' already exists (status: $existing)."
    $choice = Read-Host "  Reinstall? [y/N]"
    if ($choice -ne 'y') {
        Write-Host "  Aborted."
        exit 0
    }
    Write-Host "  Stopping and removing existing service..."
    & $NssmPath stop $ServiceName 2>$null
    & $NssmPath remove $ServiceName confirm 2>$null
    Start-Sleep -Seconds 2
}

# ── [3] Create log directory ────────────────────────────────────────────────

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ── [4] Install service ────────────────────────────────────────────────────

Write-Host "  Installing service..."
# Bind to 0.0.0.0 so DRONE nodes (via Tailscale / LAN) can reach the QUEEN.
# The firewall rules (step 8) restrict inbound to Private profile only.
& $NssmPath install $ServiceName $VenvPython "-m" "uvicorn" "main:app" "--host" "0.0.0.0" "--port" "8000"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [!] Service installation failed." -ForegroundColor Red
    exit 1
}

# ── [5] Configure service ──────────────────────────────────────────────────

Write-Host "  Configuring service parameters..."

# Working directory
& $NssmPath set $ServiceName AppDirectory $AgentDir

# Display name and description
& $NssmPath set $ServiceName DisplayName "Layla AI Assistant"
& $NssmPath set $ServiceName Description "Always-on AI personal assistant with distributed compute"

# Auto-start on boot
& $NssmPath set $ServiceName Start SERVICE_AUTO_START

# Restart on failure (10-second delay)
& $NssmPath set $ServiceName AppRestartDelay 10000

# Below Normal priority (user apps get priority)
& $NssmPath set $ServiceName AppPriority BELOW_NORMAL_PRIORITY_CLASS

# Logging
$LogStdout = Join-Path $LogDir "service-stdout.log"
$LogStderr = Join-Path $LogDir "service-stderr.log"
& $NssmPath set $ServiceName AppStdout $LogStdout
& $NssmPath set $ServiceName AppStderr $LogStderr
& $NssmPath set $ServiceName AppStdoutCreationDisposition 4  # Append
& $NssmPath set $ServiceName AppStderrCreationDisposition 4  # Append
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 10485760  # 10MB

# Environment: inherit current user PATH + add venv
$venvScripts = Join-Path $RepoRoot ".venv\Scripts"
& $NssmPath set $ServiceName AppEnvironmentExtra "PATH=$venvScripts;$env:PATH"

Write-Host ""
Write-Host "  Service '$ServiceName' installed successfully." -ForegroundColor Green
Write-Host ""
Write-Host "  Commands:"
Write-Host "    Start:   nssm start $ServiceName"
Write-Host "    Stop:    nssm stop $ServiceName"
Write-Host "    Status:  nssm status $ServiceName"
Write-Host "    Restart: nssm restart $ServiceName"
Write-Host "    Remove:  nssm remove $ServiceName confirm"
Write-Host ""

# ── [6] Optionally start now ───────────────────────────────────────────────

$startNow = Read-Host "  Start Layla service now? [Y/n]"
if ($startNow -ne 'n') {
    & $NssmPath start $ServiceName
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "  Layla is running!" -ForegroundColor Green
        Write-Host "  Open http://localhost:8000/ui in your browser."
        Write-Host ""
    } else {
        Write-Host "  [!] Failed to start. Check logs at: $LogDir" -ForegroundColor Yellow
    }
}

# ── [7] Remove ScheduledTask if it exists (service supersedes it) ──────────

try {
    $task = Get-ScheduledTask -TaskName "Jinx Agent Server" -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "  Removing old ScheduledTask 'Jinx Agent Server' (service replaces it)..."
        Unregister-ScheduledTask -TaskName "Jinx Agent Server" -Confirm:$false
        Write-Host "  Done."
    }
} catch {}

# ── [8] Firewall rules for cluster networking ─────────────────────────────

Write-Host ""
Write-Host "  Setting up firewall rules for cluster networking..."
try {
    # Allow Layla API port for Tailscale and LAN peers
    $existingRule = Get-NetFirewallRule -DisplayName "Layla API (TCP 8000)" -ErrorAction SilentlyContinue
    if (-not $existingRule) {
        New-NetFirewallRule `
            -DisplayName "Layla API (TCP 8000)" `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort 8000 `
            -Action Allow `
            -Profile Private `
            -Description "Allow inbound connections to Layla AI Assistant for cluster networking" | Out-Null
        Write-Host "  Firewall rule 'Layla API (TCP 8000)' created (Private profile)." -ForegroundColor Green
    } else {
        Write-Host "  Firewall rule 'Layla API (TCP 8000)' already exists."
    }

    # Allow mDNS for zero-config LAN discovery
    $mdnsRule = Get-NetFirewallRule -DisplayName "Layla mDNS (UDP 5353)" -ErrorAction SilentlyContinue
    if (-not $mdnsRule) {
        New-NetFirewallRule `
            -DisplayName "Layla mDNS (UDP 5353)" `
            -Direction Inbound `
            -Protocol UDP `
            -LocalPort 5353 `
            -Action Allow `
            -Profile Private `
            -Description "Allow mDNS for Layla zero-config node discovery" | Out-Null
        Write-Host "  Firewall rule 'Layla mDNS (UDP 5353)' created (Private profile)." -ForegroundColor Green
    } else {
        Write-Host "  Firewall rule 'Layla mDNS (UDP 5353)' already exists."
    }
} catch {
    Write-Host "  [!] Firewall setup requires admin privileges. Skipping." -ForegroundColor Yellow
    Write-Host "      Run this script as Administrator to add firewall rules."
    Write-Host "      Or manually allow TCP port 8000 and UDP port 5353 (Private profile)."
}

Write-Host ""
