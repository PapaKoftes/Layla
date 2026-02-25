# Full setup and test - paste this entire block into PowerShell, or run:
# powershell -ExecutionPolicy Bypass -File "C:\Users\minam\local-jinx-agent\SETUP-AND-TEST.ps1"

$AgentDir = "$env:USERPROFILE\local-jinx-agent\agent"
$Launcher = "$env:USERPROFILE\local-jinx-agent\Start-Cursor-With-Jinx.ps1"

Write-Host "=== 1. Go to agent dir ===" -ForegroundColor Cyan
Set-Location $AgentDir

Write-Host "=== 2. Activate venv ===" -ForegroundColor Cyan
& "$AgentDir\venv\Scripts\Activate.ps1"

Write-Host "=== 3. Install/repair dependencies (langchain<1 so Jinx starts) ===" -ForegroundColor Cyan
python -m pip install -r requirements.txt

Write-Host "=== 4. Quick import test (catch startup errors) ===" -ForegroundColor Cyan
$importErr = $null
try {
    $null = python -c "import main; print('main.py imports OK')"
} catch {
    $importErr = $_
}
if ($importErr) {
    Write-Warning "Import failed. Run manually: python -c 'import main'"
    exit 1
}

Write-Host "=== 5. Start Jinx server in background ===" -ForegroundColor Cyan
$job = Start-Job -ScriptBlock {
    Set-Location $using:AgentDir
    & "$using:AgentDir\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
}
Start-Sleep -Seconds 5

Write-Host "=== 6. Test /v1/models (retry a few times; model may still be loading) ===" -ForegroundColor Cyan
$url = "http://127.0.0.1:8000/v1/models"
$ok = $false
foreach ($i in 1..10) {
    try {
        $r = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 10
        if ($r.data) {
            Write-Host "OK: Server returned $($r.data.Count) model(s): $(($r.data | ForEach-Object { $_.id }) -join ', ')" -ForegroundColor Green
            $ok = $true
            break
        }
    } catch {
        Write-Host "  Attempt $i failed, retrying in 3s..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
}

if (-not $ok) {
    Write-Warning "Server did not respond in time. You can still start Cursor with the launcher; first request may be slow."
}

Write-Host "=== 7. Stop background server job ===" -ForegroundColor Cyan
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue

Write-Host "`n=== Done. To use Jinx in Cursor, run the launcher ===" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$Launcher`"" -ForegroundColor White
Write-Host "Then in Cursor: set Override OpenAI Base URL to http://127.0.0.1:8000/v1 and pick model jinx (or gpt-4o-mini)." -ForegroundColor White
