<#
  packaged_smoke.ps1 - the release gate that would have caught BOTH the 1.7.5 launcher crash and the
  1.7.x degraded-embedder bug.

  CI tests the code from *source*, which always worked. These bugs were packaging-only: they only appear
  with the bundled *embeddable* Python (isolated mode) + the frozen launcher. So after building the
  payload, we run the REAL packaged bits and assert:
    1. the launcher starts the engine and /health returns 200   (catches the launcher/import bug)
    2. the embedder actually loads in the packaged Python        (catches the sentence-transformers vs
                                                                   transformers version break)
  Any failure exits non-zero, which fails the release build - a broken installer cannot ship.

  ASCII-only on purpose: Windows PowerShell 5.1 reads a no-BOM file as ANSI, so a stray em-dash breaks
  parsing. Keep it plain ASCII.

  Usage:  ./installer/packaged_smoke.ps1  [-PayloadDir installer\payload\Layla] [-Port 8199]
#>
[CmdletBinding()]
param(
  [string]$PayloadDir = "",
  [int]$Port = 8199
)
$ErrorActionPreference = "Stop"
if (-not $PayloadDir) { $PayloadDir = Join-Path $PSScriptRoot "payload\Layla" }
$py = Join-Path $PayloadDir "python\python.exe"
$agent = Join-Path $PayloadDir "agent"
$exe = Join-Path $PayloadDir "layla.exe"
foreach ($p in @($py, $exe, (Join-Path $agent "main.py"))) {
  if (-not (Test-Path $p)) { Write-Error ("packaged_smoke: missing {0} - payload is incomplete" -f $p); exit 2 }
}
$data = Join-Path $env:TEMP ("layla_smoke_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $data | Out-Null
$env:LAYLA_DATA_DIR = $data
$env:LAYLA_INSTALL_ROOT = $PayloadDir
$env:LAYLA_NO_DIALOG = "1"

$fail = 0

# Check 2 first (cheap, no server): the embedder must load in the PACKAGED python.
Write-Host "==> smoke: embedder loads in packaged python"
& $py (Join-Path $PSScriptRoot "embed_probe.py") $agent
if ($LASTEXITCODE -ne 0) { Write-Host "   FAIL: embedder did not load (degraded semantic memory would ship)"; $fail = 1 }
else { Write-Host "   OK" }

# Check 1: the REAL frozen layla.exe (the shipped launcher) starts the engine and /health is 200.
# This exercises exactly what a user double-clicks — the frozen exe + embeddable Python together, which is
# where the 1.7.5 boot crash lived. (layla.exe is windowed/console=False, so it writes no stdout; the
# launcher tees the engine to launch.log, which we read on failure.)
Write-Host ("==> smoke: layla.exe boots the engine (/health 200 on port {0})" -f $Port)
$proc = Start-Process -FilePath $exe -ArgumentList @("--port", "$Port", "--no-tray") `
          -WorkingDirectory $PayloadDir -PassThru -WindowStyle Hidden
$healthy = $false
for ($i = 0; $i -lt 120; $i++) {
  Start-Sleep -Seconds 1
  try {
    if ((Invoke-WebRequest ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200) { $healthy = $true; break }
  } catch { }
  if ($proc.HasExited) { break }
}
if (-not $healthy) {
  Write-Host "   FAIL: engine never became healthy"
  $log = Join-Path $data "logs\launch.log"
  if (Test-Path $log) { Write-Host "--- launch.log ---"; Get-Content $log -Tail 30 }
  $fail = 1
} else { Write-Host "   OK" }

try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch { }
Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue

if ($fail -ne 0) { Write-Error "packaged_smoke: FAILED - refusing to ship a broken build"; exit 1 }
Write-Host "==> packaged smoke PASSED"
