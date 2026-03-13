Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$AgentDir = "$env:USERPROFILE\local-layla-agent\agent"
$VenvPython = Join-Path $AgentDir "venv\Scripts\python.exe"

$BindHost = "127.0.0.1"
$Port = 8000

if (-not (Test-Path -LiteralPath $VenvPython)) {
  Write-Error "Virtualenv Python not found: $VenvPython"
  exit 1
}

. (Join-Path $AgentDir "venv\Scripts\Activate.ps1")

if (-not $env:LAYLA_WORKSPACE_ROOT) { $env:LAYLA_WORKSPACE_ROOT = $env:USERPROFILE }
if (-not $env:LAYLA_AGENT_URL)      { $env:LAYLA_AGENT_URL = "http://$BindHost`:$Port" }

Write-Host ""
Write-Host "Starting server on $BindHost`:$Port ..."
Write-Host ""

$server = Start-Process -FilePath $VenvPython `
  -ArgumentList "-m","uvicorn","main:app","--host",$BindHost,"--port",$Port `
  -WorkingDirectory $AgentDir `
  -PassThru

# Wait for /health
$health = "http://$BindHost`:$Port/health"
$ready = $false
for ($i=0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 700
  try {
    $r = Invoke-RestMethod -Uri $health -TimeoutSec 2
    if ($r.ok) { $ready = $true; break }
  } catch {}
}

if ($ready) { Write-Host "Ready: $health" } else { Write-Warning "No readiness yet (may still be loading)." }

Write-Host ""
Write-Host "Launching TUI..."
Write-Host ""

Push-Location $AgentDir
try { & $VenvPython "tui.py" }
finally { Pop-Location }

if ($server -and -not $server.HasExited) { $server.Kill() }

Write-Host ""
Write-Host "Done."
Read-Host
