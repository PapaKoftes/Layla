# ============================================================================
# Layla - Clean Uninstaller
# Removes: Windows Service, venv, models (optional), data (optional)
#
#   -Purge   Non-interactive COMPLETE wipe: venv + models + data + config +
#            knowledge + logs, no prompts. Everything the installer created is
#            removed (the shared uv-managed Python is left - other apps use it).
# ============================================================================
param(
    [switch]$Purge   # wipe everything the installer created, no questions asked
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host ""
Write-Host "  .  LAYLA - Uninstaller" -ForegroundColor Cyan
Write-Host "  -------------------------" -ForegroundColor DarkGray
Write-Host ""

# -- Step 1: Stop services ----------------------------------------------

Write-Host "  [1/5]  Stopping Layla services..." -ForegroundColor Yellow

# Stop Windows Service (NSSM)
$svc = Get-Service "LaylaSvc" -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "         Stopping LaylaSvc..."
    Stop-Service "LaylaSvc" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Stop Scheduled Task (legacy auto-start)
$task = Get-ScheduledTask -TaskName "Jinx Agent Server" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "         Stopping scheduled task..."
    Stop-ScheduledTask -TaskName "Jinx Agent Server" -ErrorAction SilentlyContinue
}

# Kill any running Python processes for Layla
$procs = Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
    $_.MainModule.FileName -like "*local-jinx*" -or
    $_.MainModule.FileName -like "*layla*"
}
if ($procs) {
    Write-Host "         Stopping running Layla processes..."
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "         Done." -ForegroundColor Green

# -- Step 2: Ask what to keep -------------------------------------------

Write-Host ""
if ($Purge) {
    Write-Host "  [2/5]  -Purge: removing EVERYTHING (venv, models, data, config, knowledge, logs)." -ForegroundColor Yellow
    $keepModels = "n"; $keepData = "n"; $keepKnowledge = "n"
} else {
    Write-Host "  [2/5]  What would you like to keep?" -ForegroundColor Yellow
    Write-Host "         (tip: run  uninstall.ps1 -Purge  to wipe everything without prompts)" -ForegroundColor DarkGray
    Write-Host ""

    $keepModels = Read-Host "         Keep downloaded AI models? They can be large (Y/n)"
    if (-not $keepModels) { $keepModels = "Y" }

    $keepData = Read-Host "         Keep your data, memories & conversations? (Y/n)"
    if (-not $keepData) { $keepData = "Y" }

    $keepKnowledge = Read-Host "         Keep knowledge base files? (Y/n)"
    if (-not $keepKnowledge) { $keepKnowledge = "Y" }
}

Write-Host ""

# -- Step 3: Remove service registration --------------------------------

Write-Host "  [3/5]  Removing service registrations..." -ForegroundColor Yellow

# Remove NSSM service
# uninstall.ps1 lives at the repo root, and .venv / models / agent\ are repo-root-relative - so the
# install root IS $PSScriptRoot. The old Split-Path -Parent pointed one level too high, so venv,
# models, and logs were never actually removed while the run still reported success.
$agentDir = $PSScriptRoot
$nssmPath = Join-Path $agentDir "agent\tools\nssm.exe"
if (Test-Path $nssmPath) {
    & $nssmPath remove LaylaSvc confirm 2>$null
} else {
    sc.exe delete "LaylaSvc" 2>$null
}

# Remove the inbound firewall rules install_service.ps1 created (else they orphan, pointing at
# a program that no longer exists - a security-hygiene leak). Match the exact DisplayNames.
foreach ($ruleName in @("Layla API (TCP 8000)", "Layla mDNS (UDP 5353)")) {
    try {
        if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
            Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            Write-Host "         Removed firewall rule: $ruleName" -ForegroundColor Green
        }
    } catch { }
}

# Remove Scheduled Task
Unregister-ScheduledTask -TaskName "Jinx Agent Server" -Confirm:$false -ErrorAction SilentlyContinue

# Remove the LAYLA_INSTALL_ROOT env var (the Inno path sets it machine-wide; only its own
# uninstaller removed it, so a source-tree install + Inno mix could orphan it).
foreach ($scope in @('User','Machine')) {
    try {
        if ([Environment]::GetEnvironmentVariable('LAYLA_INSTALL_ROOT', $scope)) {
            [Environment]::SetEnvironmentVariable('LAYLA_INSTALL_ROOT', $null, $scope)
            Write-Host "         Removed env var LAYLA_INSTALL_ROOT ($scope)" -ForegroundColor Green
        }
    } catch { }
}

# Shared packages we deliberately do NOT auto-remove (they may be used by other software) - list
# them so the user can uninstall manually if Layla was the only consumer.
Write-Host ""
Write-Host "         Note: these were installed via winget and are NOT auto-removed (may be shared):" -ForegroundColor DarkYellow
Write-Host "           - Python 3.12   (uninstall: winget uninstall Python.Python.3.12)" -ForegroundColor DarkGray
Write-Host "           - cloudflared   (uninstall: winget uninstall Cloudflare.cloudflared)  [only if you used the tunnel]" -ForegroundColor DarkGray

Write-Host "         Done." -ForegroundColor Green

# -- Step 4: Remove virtual environment ---------------------------------

Write-Host "  [4/5]  Removing virtual environment..." -ForegroundColor Yellow

$venvPath = Join-Path $agentDir ".venv"
if (Test-Path $venvPath) {
    Remove-Item -Recurse -Force $venvPath -ErrorAction SilentlyContinue
    Write-Host "         Removed .venv ($([math]::Round((Get-ChildItem $venvPath -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB)) MB freed)" -ForegroundColor Green
} else {
    Write-Host "         No .venv found." -ForegroundColor DarkGray
}

# -- Step 5: Remove optional data ---------------------------------------

Write-Host "  [5/5]  Cleaning up..." -ForegroundColor Yellow

$laylaHome = Join-Path $env:USERPROFILE ".layla"

# Resolve EVERY place persistent data actually lives. A DEFAULT source install does NOT set
# LAYLA_DATA_DIR, so the primary store (layla.db + its wal/shm) sits at the REPO ROOT and
# runtime_config.json (which can hold remote_api_key / tunnel_token_hash) under agent\ - NOT under
# ~/.layla, which only holds the auxiliary DBs. The old script deleted only ~/.layla yet reported
# "Data removed", leaving the real DB and secrets on disk. Cover them all here.
$dataTargets = @(
    (Join-Path $agentDir "layla.db"),
    (Join-Path $agentDir "layla.db-wal"),
    (Join-Path $agentDir "layla.db-shm"),
    (Join-Path $agentDir "agent\runtime_config.json"),
    (Join-Path $agentDir "agent\.layla"),          # legacy encryption-key dir
    $laylaHome
)
if ($env:LAYLA_DATA_DIR) { $dataTargets += $env:LAYLA_DATA_DIR }

if ($keepModels.ToLower() -eq 'n') {
    Write-Host "         Removing downloaded models..."
    $modelsDir = Join-Path $agentDir "models"
    if (Test-Path $modelsDir) { Remove-Item -Recurse -Force $modelsDir -ErrorAction SilentlyContinue }
    $modelsHome = Join-Path $laylaHome "models"
    if (Test-Path $modelsHome) { Remove-Item -Recurse -Force $modelsHome -ErrorAction SilentlyContinue }
    if ($env:LAYLA_DATA_DIR) {
        $modelsData = Join-Path $env:LAYLA_DATA_DIR "models"
        if (Test-Path $modelsData) { Remove-Item -Recurse -Force $modelsData -ErrorAction SilentlyContinue }
    }
    Write-Host "         Models removed." -ForegroundColor Green
}

if ($keepData.ToLower() -eq 'n') {
    Write-Host ""
    Write-Host "         !  WARNING: This will permanently delete ALL your data!" -ForegroundColor Red
    Write-Host "            Memories, conversations, learnings, wiki entries..." -ForegroundColor Red
    if ($Purge) { $confirm = 'DELETE' } else { $confirm = Read-Host "         Type 'DELETE' to confirm" }
    if ($confirm -eq 'DELETE') {
        $removedAny = $false
        foreach ($t in $dataTargets) {
            if ($t -and (Test-Path $t)) {
                Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
                if (-not (Test-Path $t)) { $removedAny = $true }
            }
        }
        if ($removedAny) {
            Write-Host "         Data removed (database, config/secrets, memories, conversations)." -ForegroundColor Green
        } else {
            Write-Host "         No data files were found to remove." -ForegroundColor DarkGray
        }
    } else {
        Write-Host "         Skipped - your data is safe." -ForegroundColor Yellow
    }
} elseif ($keepKnowledge.ToLower() -eq 'n') {
    $knowledgeDir = Join-Path $laylaHome "knowledge"
    if (Test-Path $knowledgeDir) {
        Remove-Item -Recurse -Force $knowledgeDir -ErrorAction SilentlyContinue
        Write-Host "         Knowledge base removed." -ForegroundColor Green
    }
}

# Remove logs
$logsDir = Join-Path $agentDir "agent\logs"
if (Test-Path $logsDir) {
    Remove-Item -Recurse -Force $logsDir -ErrorAction SilentlyContinue
}

# Remove __pycache__ directories
Get-ChildItem -Path $agentDir -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# -- Summary ------------------------------------------------------------

Write-Host ""
Write-Host "  -------------------------" -ForegroundColor DarkGray
Write-Host "  Layla has been removed." -ForegroundColor Cyan

if ($keepData.ToLower() -ne 'n') {
    Write-Host ""
    Write-Host "  Your data is preserved at: $laylaHome" -ForegroundColor DarkGray
    Write-Host "  Re-install anytime to continue where you left off." -ForegroundColor DarkGray
}

if ($keepModels.ToLower() -ne 'n') {
    $modelsHome = Join-Path $laylaHome "models"
    if (Test-Path $modelsHome) {
        Write-Host "  Models preserved at: $modelsHome" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "  Thank you for spending time with Layla. <3" -ForegroundColor Cyan
Write-Host ""
