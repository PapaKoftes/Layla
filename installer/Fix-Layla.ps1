<#
  Fix-Layla.ps1 — hotfix for the v1.7.5 boot crash
  ("AttributeError: 'NoneType' object has no attribute 'write'" at layla_launcher.py:56).

  The bug is entirely inside the frozen launcher baked into layla.exe: with the bundled embeddable
  Python it ran the engine as `python -m uvicorn main:app`, but an embeddable Python runs isolated and
  ignores both PYTHONPATH and `-m`'s working dir, so `main:app` was unimportable and the engine died.

  This script fixes it WITHOUT reinstalling: it bypasses the frozen launcher and starts the engine with
  the already-installed embedded Python using an explicit sys.path bootstrap (exactly what v1.7.6 does),
  waits for /health, and opens the Web UI. Optionally drops a desktop shortcut so future launches are
  one click. It only READS the install dir and writes to your per-user data dir — no admin needed.

  Usage:
    powershell -ExecutionPolicy Bypass -File Fix-Layla.ps1
    powershell -ExecutionPolicy Bypass -File Fix-Layla.ps1 -InstallRoot "D:\Apps\Layla" -Port 8000
#>
[CmdletBinding()]
param(
  [string]$InstallRoot = "",
  [string]$Python = "",
  [int]$Port = 8000,
  [string]$BindHost = "127.0.0.1",
  [switch]$NoShortcut,
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"

function Find-InstallRoot {
  if ($InstallRoot) { return $InstallRoot }
  if ($env:LAYLA_INSTALL_ROOT -and (Test-Path $env:LAYLA_INSTALL_ROOT)) { return $env:LAYLA_INSTALL_ROOT }
  foreach ($c in @(
      (Join-Path ${env:ProgramFiles} "Layla"),
      (Join-Path ${env:ProgramFiles(x86)} "Layla"),
      (Join-Path $env:LOCALAPPDATA "Programs\Layla"))) {
    if ($c -and (Test-Path (Join-Path $c "agent\main.py"))) { return $c }
  }
  return $null
}

$root = Find-InstallRoot
if (-not $root) {
  Write-Host "Could not find your Layla install. Re-run with -InstallRoot pointing at the folder that" -ForegroundColor Yellow
  Write-Host "contains 'agent\main.py' (e.g. 'C:\Program Files\Layla')." -ForegroundColor Yellow
  exit 1
}
$agent = Join-Path $root "agent"
if (-not (Test-Path (Join-Path $agent "main.py"))) { Write-Host "No agent\main.py under $root" -ForegroundColor Red; exit 1 }

# Prefer the bundled embedded Python; fall back to python on PATH.
if (-not $Python) {
  $embedded = Join-Path $root "python\python.exe"
  if (Test-Path $embedded) { $Python = $embedded }
  else {
    $onPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($onPath) { $Python = $onPath } else { Write-Host "No embedded python\python.exe and no python on PATH." -ForegroundColor Red; exit 1 }
  }
}
Write-Host "Install : $root"
Write-Host "Python  : $Python"
Write-Host "Engine  : http://${BindHost}:$Port"

# Embedder fix (the 1.7.7 change): a fresh 1.7.x install is missing model2vec, so semantic memory falls
# back to a broken transformers path and degrades to keyword-only. Install it into THIS install's Python
# so memory works. Best-effort + idempotent (skips instantly if already present); needs a network once.
try {
  & $Python -c "import model2vec" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Fixing semantic memory (installing model2vec)..." -ForegroundColor Cyan
    & $Python -m pip install "model2vec>=0.5,<1" --quiet --disable-pip-version-check --no-warn-script-location
    if ($LASTEXITCODE -eq 0) { Write-Host "  memory fix applied." -ForegroundColor Green }
    else { Write-Host "  (model2vec install skipped - check your connection; the app still runs)" -ForegroundColor DarkYellow }
  } else { Write-Host "Memory  : model2vec already present." }
} catch { Write-Host "  (model2vec step skipped: $_)" -ForegroundColor DarkYellow }

# Per-user data dir (same default the app uses); never needs admin.
if (-not $env:LAYLA_DATA_DIR) { $env:LAYLA_DATA_DIR = Join-Path $env:LOCALAPPDATA "Layla" }
$env:LAYLA_INSTALL_ROOT = $root
$logDir = Join-Path $env:LAYLA_DATA_DIR "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "launch.log"

# Models folder fix: a packaged install downloads models into <install>\models, which under Program Files
# needs admin -> the Models page download fails and you get "Service temporarily unavailable" (no model).
# Point models_dir at the writable per-user data dir so downloads work with no admin.
$modelsDir = Join-Path $env:LAYLA_DATA_DIR "models"
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null
$cfgPath = Join-Path $env:LAYLA_DATA_DIR "runtime_config.json"
$configChanged = $false
try {
  $cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
  $cur = if ($cfg.PSObject.Properties.Name -contains 'models_dir') { [string]$cfg.models_dir } else { '' }
  if (-not $cur -or $cur -like "*Program Files*" -or $cur -like "$root*") {
    $cfg | Add-Member -NotePropertyName models_dir -NotePropertyValue $modelsDir -Force
    ($cfg | ConvertTo-Json -Depth 30) | Set-Content -Path $cfgPath -Encoding UTF8
    $configChanged = $true
    Write-Host "Models  : set to writable folder -> $modelsDir" -ForegroundColor Green
  } else { Write-Host "Models  : using $cur" }
} catch { Write-Host "  (models_dir config step skipped: $_)" -ForegroundColor DarkYellow }

# The fix: explicit sys.path bootstrap the isolated embeddable Python DOES honor. Written to a small
# .py file (not passed via `-c`) so no shell quoting can mangle it.
$bootPy = Join-Path $env:LAYLA_DATA_DIR "hotfix_engine.py"
@"
import os, sys
sys.path.insert(0, r"$agent")
import uvicorn
uvicorn.run("main:app", host="$BindHost", port=$Port)
"@ | Set-Content -Path $bootPy -Encoding UTF8

# Already running?
function Test-Health { try { (Invoke-WebRequest "http://${BindHost}:$Port/health" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch { $false } }
# If the config changed, a running engine still holds the OLD config -> restart it so models_dir takes
# effect. Kill whatever is listening on the port (the engine), then relaunch below.
if ($configChanged -and (Test-Health)) {
  Write-Host "Restarting Layla to apply the fix..." -ForegroundColor Cyan
  try {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique |
      ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  } catch { }
  Start-Sleep -Seconds 2
}
if (Test-Health) {
  Write-Host "Layla is already running." -ForegroundColor Green
} else {
  Write-Host "Starting Layla engine..." -ForegroundColor Cyan
  $p = Start-Process -FilePath $Python -ArgumentList @("`"$bootPy`"") -WorkingDirectory $agent `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
  $ready = $false
  for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Health) { $ready = $true; break }
    if ($p.HasExited) { break }
  }
  if (-not $ready) {
    Write-Host "Engine did not become ready. The real error is in:" -ForegroundColor Red
    Write-Host "  $log" -ForegroundColor Red
    if (Test-Path "$log.err") { Get-Content "$log.err" -Tail 20 }
    exit 1
  }
  Write-Host "Layla is up." -ForegroundColor Green
}

if (-not $NoBrowser) { Start-Process "http://${BindHost}:$Port/ui" }

# A reusable shortcut so the friend never touches the broken exe again.
if (-not $NoShortcut) {
  try {
    $ps1 = $MyInvocation.MyCommand.Path
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Layla (fixed).lnk"
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = "powershell.exe"
    $s.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1`""
    $s.WorkingDirectory = (Split-Path $ps1)
    $s.IconLocation = (Join-Path $root "layla.exe")
    $s.Save()
    Write-Host "Desktop shortcut created: Layla (fixed)" -ForegroundColor Green
  } catch { Write-Host "(Could not create desktop shortcut: $_)" -ForegroundColor DarkYellow }
}
Write-Host "Done. Leave this window open; closing it stops Layla." -ForegroundColor Cyan
