# Download Jinx 20B GGUF from Hugging Face into local-jinx-agent\models\ and save as your-model.gguf
# Quantization: Q4_K_M = good quality/size balance (~15.8 GB). Change $FileName to use another (see list below).

$ModelsDir = "$env:USERPROFILE\local-jinx-agent\models"
$OutFile   = Join-Path $ModelsDir "your-model.gguf"

# Hugging Face repo: Jinx-org/Jinx-gpt-oss-20b-GGUF
# Available: Q2_K (12.1 GB), Q3_K_S (12.1), Q3_K_M (12.9), Q4_K_S (14.7), Q4_K_M (15.8), Q5_K_S (15.9), Q5_K_M (16.9), Q6_K (22.2), Q8_0 (22.3)
$FileName  = "jinx-gpt-oss-20b-Q4_K_M.gguf"
$BaseUrl   = "https://huggingface.co/Jinx-org/Jinx-gpt-oss-20b-GGUF/resolve/main"
$Url       = "$BaseUrl/$FileName"

if (-not (Test-Path $ModelsDir)) {
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
}

if (Test-Path $OutFile) {
    $ans = Read-Host "File already exists: $OutFile. Overwrite? (y/N)"
    if ($ans -ne "y" -and $ans -ne "Y") { exit 0 }
}

Write-Host "Downloading $FileName from Hugging Face..." -ForegroundColor Cyan
Write-Host "URL: $Url" -ForegroundColor Gray
Write-Host "Saving as: $OutFile" -ForegroundColor Gray
Write-Host ""

try {
    # Use Bypass for TLS in case of cert issues; -UseBasicParsing for headless
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 3600
    Write-Host "Done. Model saved to: $OutFile" -ForegroundColor Green
    Write-Host ""
    Write-Host "Jinx is ready. To use in Cursor:" -ForegroundColor Cyan
    Write-Host "  1. Run: powershell -ExecutionPolicy Bypass -File `"$env:USERPROFILE\local-jinx-agent\Start-Cursor-With-Jinx.ps1`"" -ForegroundColor White
    Write-Host "  2. In Cursor: Settings -> Models -> Override OpenAI Base URL = http://127.0.0.1:8000/v1 , Model = jinx" -ForegroundColor White
    Write-Host "  3. In chat, select Jinx from the dropdown and send a message. First reply may take 30-60s while the model loads." -ForegroundColor White
} catch {
    Write-Host "Download failed: $_" -ForegroundColor Red
    Write-Host "If you get 401/403, the repo may be gated. In that case:" -ForegroundColor Yellow
    Write-Host "  1. Go to https://huggingface.co/Jinx-org/Jinx-gpt-oss-20b-GGUF" -ForegroundColor Yellow
    Write-Host "  2. Accept the agreement / log in." -ForegroundColor Yellow
    Write-Host "  3. Download a GGUF file manually and save it as: $OutFile" -ForegroundColor Yellow
    exit 1
}
