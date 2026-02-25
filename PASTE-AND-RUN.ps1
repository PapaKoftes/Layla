# ========== FULL SETUP AND TEST - paste this entire block into PowerShell ==========
# Or run: powershell -ExecutionPolicy Bypass -File "C:\Users\minam\local-jinx-agent\PASTE-AND-RUN.ps1"

$AgentDir = "$env:USERPROFILE\local-jinx-agent\agent"
$Launcher = "$env:USERPROFILE\local-jinx-agent\Start-Cursor-With-Jinx.ps1"

Write-Host "`n=== 1. Go to agent dir ===" -ForegroundColor Cyan
Set-Location $AgentDir

Write-Host "=== 2. Activate venv ===" -ForegroundColor Cyan
& "$AgentDir\venv\Scripts\Activate.ps1"

Write-Host "=== 3. Ensure deps (langchain-community, fastapi, uvicorn, py_mini_racer) ===" -ForegroundColor Cyan
& "$AgentDir\venv\Scripts\python.exe" -m pip install langchain-community fastapi "uvicorn[standard]" py_mini_racer --quiet

Write-Host "=== 4. Import test ===" -ForegroundColor Cyan
$out = & "$AgentDir\venv\Scripts\python.exe" -c "import main; print('OK')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "IMPORT FAILED:" -ForegroundColor Red
    Write-Host $out
    exit 1
}
Write-Host "main.py imports OK" -ForegroundColor Green

Write-Host "`n=== 5. Start Jinx server in background ===" -ForegroundColor Cyan
$proc = Start-Process -FilePath "$AgentDir\venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $AgentDir -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 8

Write-Host "=== 6. Test GET /v1/models ===" -ForegroundColor Cyan
$url = "http://127.0.0.1:8000/v1/models"
$ok = $false
foreach ($i in 1..6) {
    try {
        $r = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 15
        if ($r.data) {
            Write-Host "SUCCESS: Server returned models: $(($r.data | ForEach-Object { $_.id }) -join ', ')" -ForegroundColor Green
            $ok = $true
            break
        }
    } catch {
        Write-Host "  Attempt $i failed, retrying in 3s..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
}
if (-not $ok) {
    if ($proc.HasExited) {
        Write-Host "Server exited (code $($proc.ExitCode)). Check: $env:USERPROFILE\local-jinx-agent\jinx-server-error.log" -ForegroundColor Red
    } else {
        Write-Host "Server may still be loading model. Try the launcher; first request can be slow." -ForegroundColor Yellow
    }
}

if ($proc -and -not $proc.HasExited) { $proc.Kill() }

Write-Host "`n=== 7. To use Jinx in Cursor ===" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$Launcher`"" -ForegroundColor Cyan
Write-Host "  Cursor: Override OpenAI Base URL = http://127.0.0.1:8000/v1 , Model = jinx" -ForegroundColor White
Write-Host ""
