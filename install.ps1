# Layla — Windows PowerShell installer
# Creates virtualenv, installs dependencies, runs interactive installer

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "  ∴  LAYLA — Installer (Windows)" -ForegroundColor Cyan
Write-Host "  ──────────────────────────────────────"
Write-Host ""

# ── [1/6] Python check ───────────────────────────────────────────────────────
Write-Host "  [1/6]  Checking Python..."
try {
    $pyVersion = python --version 2>&1
    if (-not $pyVersion) { throw "Python not found" }
    Write-Host "      $pyVersion found."
} catch {
    Write-Host ""
    Write-Host "  [!] Python not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install Python 3.11 or 3.12 from https://www.python.org/downloads/"
    Write-Host "  IMPORTANT: Check 'Add Python to PATH' during install."
    Write-Host ""
    exit 1
}

$verCheck = python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  [!] Python 3.11 or 3.12 is required (3.13+ not supported yet)." -ForegroundColor Red
    Write-Host ""
    exit 1
}
Write-Host ""

# ── [2/6] Virtual environment ───────────────────────────────────────────────
Write-Host "  [2/6]  Creating virtual environment..."
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "      .venv already exists, skipping."
} else {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [!] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "      Done."
}
Write-Host ""

# Activate venv
& .\.venv\Scripts\Activate.ps1

# ── [3/6] Dependencies ───────────────────────────────────────────────────────
Write-Host "  [3/6]  Installing dependencies (this may take 5–15 minutes)..."
Write-Host "        llama-cpp-python compiles on first install — be patient."
Write-Host ""
pip install -q --upgrade pip
pip install -r agent\requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  [!] Dependency install failed." -ForegroundColor Red
    Write-Host "      Check your internet connection and try again."
    Write-Host ""
    exit 1
}
Write-Host "      Dependencies installed."
Write-Host ""

# ── [4/6] Playwright browser ────────────────────────────────────────────────
Write-Host "  [4/6]  Setting up browser automation (Playwright)..."
playwright install chromium 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "      Browser ready."
} else {
    Write-Host "      [note] Playwright setup skipped — browser tools may be limited."
    Write-Host "        Run 'playwright install chromium' later if needed."
}
Write-Host ""

# ── [5/8] Config wizard + verify ─────────────────────────────────────────────
Write-Host "  [5/8]  Detecting hardware, setting up config, and verifying..."
Write-Host ""
python agent\install\run_first_time.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  [!] Setup had issues. See above for details." -ForegroundColor Yellow
    Write-Host "      Run: python agent\diagnose_startup.py"
    Write-Host "      See: knowledge\troubleshooting.md"
    Write-Host ""
}
Write-Host ""

# ── [6/8] Setup Wizard (purpose, node role, cluster) ────────────────────────
Write-Host "  [6/8]  Running setup wizard (purpose, node role, cluster)..."
Write-Host ""
python agent\install\setup_wizard.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  [!] Setup wizard had issues. See above for details." -ForegroundColor Yellow
    Write-Host "      You can re-run later: python agent\install\setup_wizard.py"
    Write-Host ""
}
Write-Host ""

# ── [7/8] Service install (optional) ────────────────────────────────────────
Write-Host "  [7/8]  Windows Service setup..."
$installService = Read-Host "  Install Layla as a Windows Service (always-on, auto-start at boot)? [Y/n]"
if ($installService -ne 'n') {
    try {
        & "$PSScriptRoot\agent\install\install_service.ps1"
    } catch {
        Write-Host "  [!] Service install failed: $_" -ForegroundColor Yellow
        Write-Host "      You can retry later: agent\install\install_service.ps1"
    }
} else {
    Write-Host "      Skipped. Run agent\install\install_service.ps1 later to install."
}
Write-Host ""

# ── [8/8] Launchers ─────────────────────────────────────────────────────────
Write-Host "  [8/8]  Creating launch shortcut..."
if (-not (Test-Path "START.bat")) {
    @"
@echo off
setlocal
title Layla
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -c "import json,pathlib; c=pathlib.Path('agent/runtime_config.json'); cfg=json.loads(c.read_text()) if c.exists() else {}; m=cfg.get('model_filename',''); md=cfg.get('models_dir',''); p=pathlib.Path(md).expanduser()/m if md and m else pathlib.Path('models')/m if m else None; exit(0 if p and p.exists() else 1)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [!] No model found. Run python agent\install\installer_cli.py or see MODELS.md
  echo.
  pause & exit /b 1
)
echo.
echo   Layla - http://localhost:8000/ui
echo   Press Ctrl+C to stop.
echo.
start "" http://localhost:8000/ui
cd agent
uvicorn main:app --host 0.0.0.0 --port 8000
"@ | Out-File -FilePath "START.bat" -Encoding ASCII
}
Write-Host "      START.bat ready."
Write-Host ""

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host "  ═══════════════════════════════════════════════"
Write-Host "   INSTALLATION COMPLETE"
Write-Host "  ═══════════════════════════════════════════════"
Write-Host ""
Write-Host "   If the setup wizard didn't download a model:"
Write-Host "   • Open MODELS.md to pick one for your hardware"
Write-Host "   • Put the .gguf file in  ~/.layla/models/  or  models/"
Write-Host "   • Run  python agent\install\installer_cli.py  to configure"
Write-Host ""
Write-Host "   When you have a model:  double-click  START.bat"
Write-Host "   Layla opens at:         http://localhost:8000/ui"
Write-Host ""
Write-Host "  ═══════════════════════════════════════════════"
Write-Host ""
