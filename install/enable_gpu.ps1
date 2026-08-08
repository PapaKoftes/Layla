# Layla - turn on NVIDIA GPU acceleration for an EXISTING install.
#
# Use this when you already installed Layla (CPU build) and want it to run on your
# NVIDIA GPU without reinstalling everything. It swaps ONLY the llama.cpp build
# (CPU -> CUDA) and points the config at the GPU - the model download is untouched.
#
#   powershell -ExecutionPolicy Bypass -File install\enable_gpu.ps1
#
# Flags:
#   -Off      revert to the CPU build (undo GPU acceleration)
#   -Source   build llama.cpp from source with native kernels for THIS GPU. Needed for
#             Blackwell (RTX 50-series, compute 12.0/sm_120): the prebuilt cu124 wheel has
#             no sm_120 kernels and runs SLOWER than the CPU. Requires the CUDA Toolkit
#             (nvcc) and Visual Studio Build Tools (cl.exe) - see install/GPU_BLACKWELL.md.
#
# If the CUDA build fails to load (driver too old / missing runtime), it automatically
# reverts to the CPU build so Layla keeps working.
#
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads .ps1 as ANSI).
param(
    [switch]$Off,     # revert to the CPU build (undo GPU acceleration)
    [switch]$Source   # build native kernels from source (required for Blackwell / sm_120)
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$LlamaIndexCpu  = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
$LlamaIndexCuda = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
$LlamaSpec = "llama-cpp-python>=0.3.1,<0.4"
$LlamaSrcSpec = "llama-cpp-python==0.3.34"   # pinned for the reproducible source build
$VPy = ".\.venv\Scripts\python.exe"
$Cfg = "agent\runtime_config.json"
$Lib = ".\.venv\Lib\site-packages\llama_cpp\lib"

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

# The abetlen CUDA wheel ships ggml-cuda.dll but NOT the CUDA runtime it links against
# (cudart/cublas/cublasLt). On a box with no CUDA Toolkit installed those DLLs are missing and
# llama.dll fails to load with "Could not find module". Install them from pip (which DOES ship
# Windows DLLs) and copy them next to ggml-cuda.dll so the loader finds them. This is why the
# prebuilt GPU build could not load before - the installer's "bundles the runtime" claim was wrong.
function Add-CudaRuntimeDlls {
    Write-Host "  Ensuring CUDA runtime DLLs (cudart/cublas) sit next to ggml-cuda.dll ..." -ForegroundColor Cyan
    uv pip install --python $VPy nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 2>&1 | Out-Null
    if (-not (Test-Path $Lib)) { return }
    $sp = ".\.venv\Lib\site-packages"
    foreach ($sub in @("nvidia\cuda_runtime\bin", "nvidia\cublas\bin")) {
        $src = Join-Path $sp $sub
        if (Test-Path $src) {
            Get-ChildItem $src -Filter "*.dll" -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^(cudart64|cublas64|cublasLt64)_' } |
                ForEach-Object { Copy-Item $_.FullName $Lib -Force }
        }
    }
}

# nvidia-smi compute capability as a number (e.g. 12.0 for Blackwell / RTX 50-series), or 0.
function Get-ComputeCap {
    try {
        $out = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return [double](([string]($out | Select-Object -First 1)).Trim()) }
    } catch {}
    return 0.0
}

# Locate the CUDA Toolkit and a Visual Studio vcvars64.bat for a source build. Returns $null if missing.
function Get-CudaToolkitDir {
    if ($env:CUDA_PATH -and (Test-Path (Join-Path $env:CUDA_PATH "bin\nvcc.exe"))) { return $env:CUDA_PATH }
    $root = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if (Test-Path $root) {
        $newest = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName "bin\nvcc.exe") } |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($newest) { return $newest.FullName }
    }
    return $null
}
function Get-VcVars {
    $roots = @(
        "C:\Program Files\Microsoft Visual Studio\2022",
        "C:\Program Files (x86)\Microsoft Visual Studio\2022"
    )
    foreach ($r in $roots) {
        foreach ($ed in @("BuildTools", "Community", "Professional", "Enterprise")) {
            $vc = Join-Path $r "$ed\VC\Auxiliary\Build\vcvars64.bat"
            if (Test-Path $vc) { return $vc }
        }
    }
    return $null
}

# Build llama-cpp-python from source with kernels for THIS GPU's arch (native sm_120 on Blackwell).
# Uses the Ninja generator (the VS/MSBuild CUDA generator fails to resolve CudaToolkitDir on Windows).
function Build-LlamaFromSource([double]$cap) {
    $cuda = Get-CudaToolkitDir
    $vcvars = Get-VcVars
    if (-not $cuda)   { Write-Host "  Source build needs the CUDA Toolkit (nvcc). Install it, then re-run with -Source. See install/GPU_BLACKWELL.md." -ForegroundColor Red; return $false }
    if (-not $vcvars) { Write-Host "  Source build needs Visual Studio Build Tools with the C++ workload (cl.exe). See install/GPU_BLACKWELL.md." -ForegroundColor Red; return $false }
    $arch = if ($cap -ge 1.0) { [string][int]($cap * 10) } else { "native" }   # 12.0 -> "120"
    Write-Host "  Building llama.cpp from source for CUDA arch $arch (this takes 15-30 min) ..." -ForegroundColor Cyan
    $uvExe = (Get-Command uv).Source
    $bat = Join-Path $env:TEMP "layla_build_gpu.bat"
    $py = (Resolve-Path $VPy).Path
    @(
        '@echo off',
        "set `"CUDA_PATH=$cuda`"",
        "set `"PATH=%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;$Repo\.venv\Scripts;%PATH%`"",
        "call `"$vcvars`"",
        "if errorlevel 1 ( echo VCVARS_FAILED & exit /b 1 )",
        "set `"CMAKE_ARGS=-G Ninja -DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=$arch -DCMAKE_BUILD_TYPE=Release`"",
        "set `"FORCE_CMAKE=1`"",
        "cd /d `"$Repo`"",
        "`"$py`" -m pip install ninja",
        "`"$py`" -m pip install --no-binary llama-cpp-python `"$LlamaSrcSpec`" --force-reinstall --no-cache-dir",
        "exit /b %errorlevel%"
    ) | Set-Content -Path $bat -Encoding ASCII
    & $py -m ensurepip 2>&1 | Out-Null
    cmd /c "`"$bat`""
    if ($LASTEXITCODE -ne 0) { Write-Host "  Source build failed. See the output above." -ForegroundColor Red; return $false }
    # The source build links the installed toolkit's runtime; copy those DLLs next to the built ggml-cuda.dll.
    $tkbin = Join-Path $cuda "bin\x64"
    if (-not (Test-Path $tkbin)) { $tkbin = Join-Path $cuda "bin" }
    Get-ChildItem $tkbin -Filter "*.dll" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(cudart64|cublas64|cublasLt64)_' } |
        ForEach-Object { Copy-Item $_.FullName $Lib -Force }
    return $true
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
$Cap = Get-ComputeCap
Write-Host "  NVIDIA GPU detected: $Gpu (compute $Cap)" -ForegroundColor Green

# Blackwell (compute 12.0 / sm_120) has NO kernels in the prebuilt cu124 wheel - it runs via a slow
# fallback that is worse than the CPU. Steer these cards to the native source build.
$IsBlackwell = ($Cap -ge 12.0)
if ($IsBlackwell -and -not $Source) {
    Write-Host "  This is a Blackwell-class GPU. The prebuilt CUDA wheel has no sm_120 kernels and would" -ForegroundColor Yellow
    Write-Host "  run SLOWER than your CPU. Re-run with -Source to build native kernels (needs CUDA Toolkit" -ForegroundColor Yellow
    Write-Host "  + VS Build Tools). Proceeding with the prebuilt build only so the GPU at least loads ..." -ForegroundColor Yellow
}

if ($Source) {
    if (-not (Build-LlamaFromSource $Cap)) {
        Write-Host "  Falling back to the prebuilt CUDA wheel + runtime DLLs so Layla still runs on the GPU ..." -ForegroundColor Yellow
        uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $LlamaIndexCuda --index-strategy unsafe-best-match
        Add-CudaRuntimeDlls
    }
} else {
    Write-Host "  Installing the prebuilt CUDA llama.cpp build ..." -ForegroundColor Cyan
    uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $LlamaIndexCuda --index-strategy unsafe-best-match
    Add-CudaRuntimeDlls
}
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
if ($IsBlackwell -and -not $Source) {
    Write-Host "  NOTE: for FULL Blackwell speed (native sm_120), re-run:  install\enable_gpu.ps1 -Source" -ForegroundColor Yellow
}
Write-Host "  Restart Layla (START.bat) if it is open, and enjoy the speedup." -ForegroundColor Green
