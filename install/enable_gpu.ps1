# Layla - turn on NVIDIA GPU acceleration for an EXISTING install.
#
# Use this when you already installed Layla (CPU build) and want it to run on your
# NVIDIA GPU without reinstalling everything. It swaps ONLY the llama.cpp build
# (CPU -> CUDA) and points the config at the GPU - the model download is untouched.
#
#   powershell -ExecutionPolicy Bypass -File install\enable_gpu.ps1
#
# If the CUDA build fails to load (driver too old / missing runtime), it automatically
# reverts to the CPU build so Layla keeps working.
#
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads .ps1 as ANSI).
param(
    [switch]$Off   # revert to the CPU build (undo GPU acceleration)
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$LlamaIndexCpu  = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
$LlamaIndexCuda = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
$LlamaSpec = "llama-cpp-python>=0.3.1,<0.4"
$VPy = ".\.venv\Scripts\python.exe"
$Cfg = "agent\runtime_config.json"

if (-not (Test-Path $VPy)) {
    throw "No .venv found at $VPy. Run install\bootstrap.ps1 first, then this script."
}
function Test-Uv { try { uv --version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false } }
if (-not (Test-Uv)) {
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Test-Uv)) { throw "uv is not on PATH. Open a NEW terminal and re-run, or re-run install\bootstrap.ps1." }
}

function Set-GpuLayers([int]$n) {
    & $VPy -c "import json,pathlib,sys; p=pathlib.Path(r'$Cfg'); d=json.loads(p.read_text('utf-8')) if p.exists() else {}; d['n_gpu_layers']=int(sys.argv[1]); p.write_text(json.dumps(d,indent=2),encoding='utf-8')" $n 2>$null
}

Write-Host ""
if ($Off) {
    Write-Host "  Reverting Layla to the CPU llama.cpp build ..." -ForegroundColor Cyan
    uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $LlamaIndexCpu --index-strategy unsafe-best-match
    Set-GpuLayers 0
    Write-Host "  Done - Layla will run on the CPU. Restart it (START.bat) to apply." -ForegroundColor Green
    exit 0
}

# Detect an NVIDIA GPU (nvidia-smi only; no torch/CUDA toolkit needed).
$Gpu = $null
try {
    $out = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) { $Gpu = ([string]($out | Select-Object -First 1)).Trim() }
} catch {}
if (-not $Gpu) {
    Write-Host "  No NVIDIA GPU found (nvidia-smi did not report one)." -ForegroundColor Yellow
    Write-Host "  GPU acceleration needs an NVIDIA card with an up-to-date driver. Nothing changed." -ForegroundColor Yellow
    exit 1
}

Write-Host "  NVIDIA GPU detected: $Gpu" -ForegroundColor Green
Write-Host "  Installing the CUDA llama.cpp build (bundles the CUDA runtime - no toolkit needed) ..." -ForegroundColor Cyan
uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $LlamaIndexCuda --index-strategy unsafe-best-match
Set-GpuLayers -1

Write-Host "  Verifying the GPU build loads the model and completes a turn ..." -ForegroundColor Cyan
& $VPy scripts\selftest.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "  The CUDA build failed to run - your NVIDIA driver may be too old or a runtime DLL is missing." -ForegroundColor Yellow
    Write-Host "  Reverting to the CPU build so Layla keeps working. Update your driver and try again later." -ForegroundColor Yellow
    uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $LlamaIndexCpu --index-strategy unsafe-best-match
    Set-GpuLayers 0
    exit 1
}
Write-Host ""
Write-Host "  Done - Layla now runs on your GPU ($Gpu)." -ForegroundColor Green
Write-Host "  Restart Layla (START.bat) if it is open, and enjoy the speedup." -ForegroundColor Green
