# ============================================================================
# Layla — Clean Uninstaller
# Removes: Windows Service, venv, models (optional), data (optional)
# ============================================================================

$ErrorActionPreference = "SilentlyContinue"

Write-Host ""
Write-Host "  ∴  LAYLA — Uninstaller" -ForegroundColor Cyan
Write-Host "  ─────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# ── Step 1: Stop services ──────────────────────────────────────────────

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

# ── Step 2: Ask what to keep ───────────────────────────────────────────

Write-Host ""
Write-Host "  [2/5]  What would you like to keep?" -ForegroundColor Yellow
Write-Host ""

$keepModels = Read-Host "         Keep downloaded AI models? They can be large (Y/n)"
if (-not $keepModels) { $keepModels = "Y" }

$keepData = Read-Host "         Keep your data, memories & conversations? (Y/n)"
if (-not $keepData) { $keepData = "Y" }

$keepKnowledge = Read-Host "         Keep knowledge base files? (Y/n)"
if (-not $keepKnowledge) { $keepKnowledge = "Y" }

Write-Host ""

# ── Step 3: Remove service registration ────────────────────────────────

Write-Host "  [3/5]  Removing service registrations..." -ForegroundColor Yellow

# Remove NSSM service
$agentDir = Split-Path -Parent $PSScriptRoot
$nssmPath = Join-Path $agentDir "agent\tools\nssm.exe"
if (Test-Path $nssmPath) {
    & $nssmPath remove LaylaSvc confirm 2>$null
} else {
    sc.exe delete "LaylaSvc" 2>$null
}

# Remove the inbound firewall rules install_service.ps1 created (else they orphan, pointing at
# a program that no longer exists — a security-hygiene leak). Match the exact DisplayNames.
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

Write-Host "         Done." -ForegroundColor Green

# ── Step 4: Remove virtual environment ─────────────────────────────────

Write-Host "  [4/5]  Removing virtual environment..." -ForegroundColor Yellow

$venvPath = Join-Path $agentDir ".venv"
if (Test-Path $venvPath) {
    Remove-Item -Recurse -Force $venvPath -ErrorAction SilentlyContinue
    Write-Host "         Removed .venv ($([math]::Round((Get-ChildItem $venvPath -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB)) MB freed)" -ForegroundColor Green
} else {
    Write-Host "         No .venv found." -ForegroundColor DarkGray
}

# ── Step 5: Remove optional data ───────────────────────────────────────

Write-Host "  [5/5]  Cleaning up..." -ForegroundColor Yellow

$laylaHome = Join-Path $env:USERPROFILE ".layla"

if ($keepModels.ToLower() -eq 'n') {
    Write-Host "         Removing downloaded models..."
    $modelsDir = Join-Path $agentDir "models"
    if (Test-Path $modelsDir) { Remove-Item -Recurse -Force $modelsDir -ErrorAction SilentlyContinue }
    $modelsHome = Join-Path $laylaHome "models"
    if (Test-Path $modelsHome) { Remove-Item -Recurse -Force $modelsHome -ErrorAction SilentlyContinue }
    Write-Host "         Models removed." -ForegroundColor Green
}

if ($keepData.ToLower() -eq 'n') {
    Write-Host ""
    Write-Host "         ⚠  WARNING: This will permanently delete ALL your data!" -ForegroundColor Red
    Write-Host "            Memories, conversations, learnings, wiki entries..." -ForegroundColor Red
    $confirm = Read-Host "         Type 'DELETE' to confirm"
    if ($confirm -eq 'DELETE') {
        if (Test-Path $laylaHome) {
            Remove-Item -Recurse -Force $laylaHome -ErrorAction SilentlyContinue
            Write-Host "         Data removed." -ForegroundColor Green
        }
    } else {
        Write-Host "         Skipped — your data is safe." -ForegroundColor Yellow
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

# ── Summary ────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ─────────────────────────" -ForegroundColor DarkGray
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
Write-Host "  Thank you for spending time with Layla. 💙" -ForegroundColor Cyan
Write-Host ""
