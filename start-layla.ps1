# Start Layla: venv, deps, optional knowledge fetch, optional MCP, then server
# Run from repo root: .\start-layla.ps1
# Optional: .\start-layla.ps1 -SkipDocs -NoMCP

param(
    [switch]$SkipDocs,
    [switch]$NoMCP
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location.Path }

Set-Location $Root
Write-Host "" 
Write-Host "Layla - repo root: $Root" -ForegroundColor Cyan

$VenvPath = Join-Path $Root ".venv"

function Get-VenvPython {
    $scripts = Join-Path $VenvPath "Scripts\python.exe"
    $bin = Join-Path $VenvPath "bin\python"
    if (Test-Path $scripts) { return $scripts }
    if (Test-Path $bin) { return $bin }
    return $null
}

# 0. Create and use venv
if (-not (Get-VenvPython)) {
    Write-Host ""
    Write-Host "[0/5] Creating virtualenv at .venv..." -ForegroundColor Yellow
    python -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
$VenvPython = Get-VenvPython
if (-not $VenvPython) { throw "Could not find python in .venv (Scripts\python.exe or bin\python)" }
& $VenvPython -m pip install --upgrade pip -q

# 1. Dependencies (agent + MCP)
Write-Host ""
Write-Host "[1/5] Installing dependencies (venv)..." -ForegroundColor Yellow
& $VenvPython -m pip install -r agent/requirements.txt
if ($LASTEXITCODE -ne 0) { throw "agent pip install failed" }
if (Test-Path (Join-Path $Root "cursor-jinx-mcp\requirements.txt")) {
    & $VenvPython -m pip install -r cursor-jinx-mcp/requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "MCP deps failed (non-fatal)" -ForegroundColor DarkYellow }
}

# 2. Optional: fetch knowledge docs
if (-not $SkipDocs) {
    Write-Host ""
    Write-Host "[2/5] Fetching knowledge docs..." -ForegroundColor Yellow
    & $VenvPython agent/download_docs.py
    if ($LASTEXITCODE -ne 0) { Write-Host "download_docs failed (non-fatal)" -ForegroundColor DarkYellow }
} else {
    Write-Host ""
    Write-Host "[2/5] Skipping knowledge fetch (-SkipDocs)." -ForegroundColor Gray
}

# 3. Optional: start Cursor MCP in a new window
if (-not $NoMCP) {
    Write-Host ""
    Write-Host "[3/5] Starting Cursor MCP in a new window..." -ForegroundColor Yellow
    $safeRoot = $Root -replace "'", "''"
    $mcpCmd = "Set-Location '" + $safeRoot + "'; & '" + ($VenvPython -replace "'", "''") + "' cursor-jinx-mcp/server.py"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $mcpCmd
} else {
    Write-Host ""
    Write-Host "[3/5] MCP skipped (-NoMCP)." -ForegroundColor Gray
}

# 4. Run the server (this blocks)
Write-Host ""
Write-Host "[4/5] Starting Layla server at http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "      UI: http://127.0.0.1:8000  or  http://127.0.0.1:8000/ui" -ForegroundColor Green
Write-Host "      Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""
$AgentDir = Join-Path $Root "agent"
Set-Location $AgentDir
& $VenvPython -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
