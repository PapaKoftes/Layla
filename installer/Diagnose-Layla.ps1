<#
  Diagnose-Layla.ps1 - prints the EXACT state so a model/chat failure is unambiguous. Read-only; changes
  nothing. Paste the whole output back.  ASCII-only (PS 5.1 reads no-BOM as ANSI).
#>
[CmdletBinding()]
param([string]$InstallRoot = "", [string]$Python = "")
$ErrorActionPreference = "Continue"

function Find-Root {
  if ($InstallRoot) { return $InstallRoot }
  if ($env:LAYLA_INSTALL_ROOT -and (Test-Path (Join-Path $env:LAYLA_INSTALL_ROOT "agent\main.py"))) { return $env:LAYLA_INSTALL_ROOT }
  foreach ($c in @((Join-Path ${env:ProgramFiles} "Layla"), (Join-Path $env:LOCALAPPDATA "Programs\Layla"))) {
    if ($c -and (Test-Path (Join-Path $c "agent\main.py"))) { return $c }
  }
  return $null
}
$root = Find-Root
if (-not $root) { Write-Host "Could not find Layla install (pass -InstallRoot)."; exit 1 }
$agent = Join-Path $root "agent"
if (-not $Python) {
  $emb = Join-Path $root "python\python.exe"
  $Python = if (Test-Path $emb) { $emb } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
}
if (-not $env:LAYLA_DATA_DIR) { $env:LAYLA_DATA_DIR = Join-Path $env:LOCALAPPDATA "Layla" }
$env:LAYLA_INSTALL_ROOT = $root

Write-Host "install root : $root"
Write-Host "python       : $Python"
Write-Host "data dir     : $env:LAYLA_DATA_DIR"
Write-Host ""

Write-Host "==== runtime_config.json (raw) ===="
$cfgPath = Join-Path $env:LAYLA_DATA_DIR "runtime_config.json"
if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw } else { Write-Host "(no runtime_config.json at $cfgPath)" }
Write-Host ""

Write-Host "==== python diagnostic ===="
$dp = Join-Path $env:TEMP "layla_diagnose.py"
try {
  Invoke-WebRequest "https://raw.githubusercontent.com/PapaKoftes/Layla/master/installer/diagnose.py" -OutFile $dp -UseBasicParsing
  & $Python $dp $agent 2>&1
} catch { Write-Host "diagnostic fetch/run failed: $_" }
Write-Host ""

Write-Host "==== is the engine answering? ===="
try { Write-Host ("health: " + (Invoke-WebRequest "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing).StatusCode) } catch { Write-Host "health: NOT RUNNING on :8000" }

Write-Host ""
Write-Host "==== last 25 log lines ===="
$log = Join-Path $env:LAYLA_DATA_DIR "logs\layla.log"
if (-not (Test-Path $log)) { $log = Join-Path $env:LAYLA_DATA_DIR "logs\launch.log" }
if (Test-Path $log) { Get-Content $log -Tail 25 } else { Write-Host "(no log found)" }
Write-Host "==== END ===="
