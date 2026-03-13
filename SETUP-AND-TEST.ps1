# Layla — Quick setup and server test
# Run: powershell -ExecutionPolicy Bypass -File ".\SETUP-AND-TEST.ps1"

$ErrorActionPreference = "Stop"
$Root     = $PSScriptRoot
$AgentDir = Join-Path $Root "agent"
$VenvDir  = Join-Path $Root ".venv"

function Get-VenvPython {
    $scripts = Join-Path $VenvDir "Scripts\python.exe"
    $bin     = Join-Path $VenvDir "bin\python"
    if (Test-Path $scripts) { return $scripts }
    if (Test-Path $bin)     { return $bin }
    return $null
}

Write-Host ""
Write-Host "  Layla — Setup & Test" -ForegroundColor Magenta
Write-Host "  ====================" -ForegroundColor DarkMagenta
Write-Host ""

# 1. Create venv if needed
if (-not (Get-VenvPython)) {
    Write-Host "[1/5] Creating virtualenv at .venv..." -ForegroundColor Yellow
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
$py = Get-VenvPython
Write-Host "[1/5] Python: $py" -ForegroundColor Green

# 2. Install dependencies
Write-Host "[2/5] Installing agent dependencies..." -ForegroundColor Yellow
& $py -m pip install -r (Join-Path $AgentDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Host "[2/5] Dependencies installed." -ForegroundColor Green

# 3. Import test
Write-Host "[3/5] Import test (main.py)..." -ForegroundColor Yellow
$importOut = & $py -c "import sys; sys.path.insert(0,'$AgentDir'); import main; print('OK')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "IMPORT FAILED:" -ForegroundColor Red
    Write-Host $importOut
    exit 1
}
Write-Host "[3/5] main.py imports OK." -ForegroundColor Green

# 4. Start server briefly for connectivity test
Write-Host "[4/5] Starting server (background, port 8000)..." -ForegroundColor Yellow
$proc = Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $AgentDir -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 6

Write-Host "[5/5] Testing GET /v1/models..." -ForegroundColor Yellow
$ok = $false
foreach ($i in 1..8) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/models" -Method Get -TimeoutSec 10
        if ($r.data) {
            $ids = ($r.data | ForEach-Object { $_.id }) -join ", "
            Write-Host "[5/5] Server OK — models: $ids" -ForegroundColor Green
            $ok = $true; break
        }
    } catch {
        Write-Host "  Attempt $i — waiting..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 3
    }
}
if (-not $ok) {
    Write-Host "[5/5] Server did not respond in time." -ForegroundColor Yellow
    Write-Host "      This may mean the model is still loading. Try START.bat." -ForegroundColor Yellow
}

if ($proc -and -not $proc.HasExited) { $proc.Kill() }

Write-Host ""
Write-Host "  Setup complete. Start Layla with: START.bat  or  .\start-layla.ps1" -ForegroundColor Cyan
Write-Host "  Then open: http://localhost:8000/ui" -ForegroundColor Cyan
Write-Host ""
