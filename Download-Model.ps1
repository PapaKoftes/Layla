# Download a GGUF model for Layla from Hugging Face
# Run: powershell -ExecutionPolicy Bypass -File ".\Download-Model.ps1"
#
# Layla works with any GGUF-format model. Recommended models (uncensored, capable):
#
#   Tier | Model                          | Size    | RAM needed | Notes
#   ---- | ------------------------------ | ------- | ---------- | -----
#   1    | Dolphin-Mistral-7B-Q4_K_M      |  4.1 GB | 6 GB RAM   | Fast, uncensored, excellent instruction following
#   2    | Dolphin-Llama3-8B-Q4_K_M       |  4.9 GB | 8 GB RAM   | Newer base, very capable
#   3    | Hermes-3-Llama3.1-8B-Q4_K_M    |  4.9 GB | 8 GB RAM   | Strong reasoning, uncensored
#   4    | Dolphin-Llama3-70B-Q2_K        | 26.0 GB | 32 GB RAM  | Maximum capability, needs serious hardware
#
# After downloading, edit agent/runtime_config.json:
#   "model_filename": "the-filename-you-downloaded.gguf"

param(
    [ValidateSet("dolphin-mistral-7b", "dolphin-llama3-8b", "hermes-3-8b", "dolphin-llama3-70b", "custom")]
    [string]$Model = "",
    [string]$CustomUrl = "",
    [string]$OutputName = "your-model.gguf"
)

$ModelsDir = Join-Path $PSScriptRoot "models"

$ModelTable = @{
    "dolphin-mistral-7b" = @{
        Url  = "https://huggingface.co/TheBloke/dolphin-2.6-mistral-7B-GGUF/resolve/main/dolphin-2.6-mistral-7b.Q4_K_M.gguf"
        Name = "dolphin-2.6-mistral-7b.Q4_K_M.gguf"
        Size = "4.1 GB"
        Desc = "Dolphin Mistral 7B Q4_K_M — fast, uncensored, excellent for everyday use"
    }
    "dolphin-llama3-8b" = @{
        Url  = "https://huggingface.co/bartowski/dolphin-2.9.1-llama-3-8b-GGUF/resolve/main/dolphin-2.9.1-llama-3-8b-Q4_K_M.gguf"
        Name = "dolphin-2.9.1-llama-3-8b-Q4_K_M.gguf"
        Size = "4.9 GB"
        Desc = "Dolphin Llama3 8B Q4_K_M — newer base model, highly capable"
    }
    "hermes-3-8b" = @{
        Url  = "https://huggingface.co/bartowski/Hermes-3-Llama-3.1-8B-GGUF/resolve/main/Hermes-3-Llama-3.1-8B-Q4_K_M.gguf"
        Name = "Hermes-3-Llama-3.1-8B-Q4_K_M.gguf"
        Size = "4.9 GB"
        Desc = "Hermes 3 Llama3.1 8B Q4_K_M — strong reasoning, uncensored Hermes system prompt"
    }
    "dolphin-llama3-70b" = @{
        Url  = "https://huggingface.co/bartowski/dolphin-2.9-llama3-70b-GGUF/resolve/main/dolphin-2.9-llama3-70b-Q2_K.gguf"
        Name = "dolphin-2.9-llama3-70b-Q2_K.gguf"
        Size = "26 GB"
        Desc = "Dolphin Llama3 70B Q2_K — maximum capability, needs 32+ GB RAM"
    }
}

Write-Host ""
Write-Host "  Layla — Model Downloader" -ForegroundColor Magenta
Write-Host "  ========================" -ForegroundColor DarkMagenta
Write-Host ""

if (-not (Test-Path $ModelsDir)) {
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
}

# Interactive picker if no model param given
if (-not $Model) {
    Write-Host "  Available models:" -ForegroundColor Cyan
    Write-Host ""
    $i = 1
    $keys = $ModelTable.Keys | Sort-Object
    foreach ($k in $keys) {
        $m = $ModelTable[$k]
        Write-Host "  [$i] $($m.Name)" -ForegroundColor White
        Write-Host "      $($m.Desc)" -ForegroundColor Gray
        Write-Host "      Size: $($m.Size)  |  Key: $k" -ForegroundColor DarkGray
        Write-Host ""
        $i++
    }
    Write-Host "  [c] Enter a custom HuggingFace URL" -ForegroundColor Yellow
    Write-Host ""
    $choice = Read-Host "  Choose a model [1-$($keys.Count) or c]"
    if ($choice -eq "c") {
        $Model = "custom"
        $CustomUrl = Read-Host "  Paste HuggingFace .gguf URL"
        $OutputName = Read-Host "  Output filename (e.g. my-model.gguf)"
    } else {
        $idx = [int]$choice - 1
        if ($idx -ge 0 -and $idx -lt $keys.Count) {
            $Model = ($keys | Sort-Object)[$idx]
        } else {
            Write-Host "Invalid choice." -ForegroundColor Red
            exit 1
        }
    }
}

if ($Model -eq "custom") {
    if (-not $CustomUrl) { Write-Host "No URL provided." -ForegroundColor Red; exit 1 }
    $DownloadUrl = $CustomUrl
    $OutFile = Join-Path $ModelsDir $OutputName
} else {
    $entry = $ModelTable[$Model]
    if (-not $entry) { Write-Host "Unknown model: $Model" -ForegroundColor Red; exit 1 }
    $DownloadUrl = $entry.Url
    $OutFile = Join-Path $ModelsDir $entry.Name
    $OutputName = $entry.Name
}

Write-Host ""
Write-Host "  Downloading: $OutputName" -ForegroundColor Green
Write-Host "  From:        $DownloadUrl" -ForegroundColor DarkGray
Write-Host "  Saving to:   $OutFile" -ForegroundColor DarkGray
Write-Host ""

if (Test-Path $OutFile) {
    $ans = Read-Host "  File already exists. Overwrite? (y/N)"
    if ($ans -ne "y" -and $ans -ne "Y") { Write-Host "Cancelled."; exit 0 }
}

try {
    $wc = New-Object System.Net.WebClient
    $wc.DownloadFile($DownloadUrl, $OutFile)
    Write-Host ""
    Write-Host "  Download complete: $OutFile" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next: edit agent/runtime_config.json and set:" -ForegroundColor Cyan
    Write-Host "    `"model_filename`": `"$OutputName`"" -ForegroundColor White
    Write-Host ""
    Write-Host "  Then start Layla with START.bat or start-layla.ps1" -ForegroundColor Cyan
} catch {
    Write-Host ""
    Write-Host "  Download failed: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Manual download:" -ForegroundColor Yellow
    Write-Host "    1. Open $DownloadUrl in your browser" -ForegroundColor Yellow
    Write-Host "    2. Save the file to: $ModelsDir\" -ForegroundColor Yellow
    Write-Host "    3. Edit agent/runtime_config.json: `"model_filename`": `"$OutputName`"" -ForegroundColor Yellow
    exit 1
}
