# Layla - one-command installer (Windows / PowerShell) powered by uv.
#
# Installs Python ITSELF + every dependency, then provisions a model for your
# hardware and runs a deep self-test. No system Python, no MSVC/CMake, no admin:
# uv fetches a standalone Python and we install prebuilt wheels for llama-cpp
# + torch, so there is nothing to compile. An NVIDIA GPU is auto-detected and, when
# present, the CUDA llama.cpp build is installed so the model runs on the GPU.
#
#   git clone https://github.com/PapaKoftes/Layla.git
#   cd Layla
#   powershell -ExecutionPolicy Bypass -File install\bootstrap.ps1
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI when
# there is no BOM, so non-ASCII punctuation breaks parsing.
#
# Options:
#   -Prefer quality|balanced|lite|speed   model bias for detected hardware (default balanced)
#   -Accel auto|gpu|cpu                   NVIDIA GPU offload: auto-detect (default), force on, or force off
#   -SkipModel                            set up the env but don't download a model yet
#   -Verify                               skip install; just run the deep self-test
param(
    [ValidateSet("quality", "balanced", "lite", "speed")][string]$Prefer = "balanced",
    [ValidateSet("auto", "gpu", "cpu")][string]$Accel = "auto",
    [switch]$SkipModel,
    [switch]$Verify,
    [switch]$NoStart   # skip auto-launching Layla at the end (CI/automation)
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot          # install\ -> repo root
Set-Location $Repo

Write-Host ""
Write-Host "  Layla - installer (uv, compiler-free)" -ForegroundColor Magenta
Write-Host "  -------------------------------------"

$LlamaIndexCpu  = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
$LlamaIndexCuda = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
$LlamaSpec = "llama-cpp-python>=0.3.1,<0.4"
$VPy = ".\.venv\Scripts\python.exe"

function Test-Uv {
    try { uv --version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

function Get-NvidiaGpu {
    # Return the GPU name if nvidia-smi reports one, else $null. Uses nvidia-smi only
    # (no torch, no CUDA toolkit) - the app's own hardware probe queries the same tool.
    try {
        $out = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -First 1)).Trim() }
    } catch {}
    return $null
}

# CPU vs CUDA llama.cpp build. GPU offload (n_gpu_layers, set by provision_model when a GPU is
# detected) does NOTHING unless the CUDA wheel is installed - the CPU wheel silently ignores it.
# Auto-detect an NVIDIA card; -Accel gpu|cpu forces it. The CUDA wheel ships ggml-cuda.dll but NOT
# the CUDA runtime it links against, so Add-CudaRuntimeDlls installs cudart/cublas from pip wheels
# next to it - without that the wheel fails to load on a box with no CUDA Toolkit. If it still fails
# to load, the self-test step falls back to the CPU wheel so the install always ends up working.
# NOTE: Blackwell (RTX 50-series / sm_120) needs NATIVE kernels the prebuilt wheel lacks - it will
# load but run slower than CPU; use  install\enable_gpu.ps1 -Source  to build them (see GPU_BLACKWELL.md).
function Add-CudaRuntimeDlls {
    # Run uv BARE here (no 2>&1, no *>$null, no |Out-Null). Under Windows PowerShell 5.1
    # with $ErrorActionPreference='Stop', ANY redirection of a native command's stderr wraps
    # uv's benign progress lines ("Resolved N packages") as a NativeCommandError and ABORTS
    # the whole install. Left bare, uv's output just goes to the console and the install
    # proceeds (matching every other `uv pip install` call in this script). The DLL-copy
    # below and the self-test's CPU fallback already handle a genuine cudart failure.
    uv pip install --python $VPy nvidia-cuda-runtime-cu12 nvidia-cublas-cu12
    $lib = ".\.venv\Lib\site-packages\llama_cpp\lib"
    $sp  = ".\.venv\Lib\site-packages"
    if (-not (Test-Path $lib)) { return }
    foreach ($sub in @("nvidia\cuda_runtime\bin", "nvidia\cublas\bin")) {
        $src = Join-Path $sp $sub
        if (Test-Path $src) {
            Get-ChildItem $src -Filter "*.dll" -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^(cudart64|cublas64|cublasLt64)_' } |
                ForEach-Object { Copy-Item $_.FullName $lib -Force }
        }
    }
}
$Gpu = $null
if ($Accel -ne "cpu") { $Gpu = Get-NvidiaGpu }
if ($Accel -eq "gpu" -and -not $Gpu) {
    Write-Host "  -Accel gpu requested but no NVIDIA GPU found (nvidia-smi). Using the CPU build." -ForegroundColor Yellow
}
$UseGpu = [bool]$Gpu
$LlamaIndex = if ($UseGpu) { $LlamaIndexCuda } else { $LlamaIndexCpu }

# 1) ensure uv (single static binary; needs no Python, no admin)
if (-not (Test-Uv)) {
    Write-Host "[1/7] Installing uv (Astral) ..."
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Test-Uv)) {
    throw "uv is installed but not on PATH. Open a NEW terminal and re-run install\bootstrap.ps1."
}
Write-Host "[1/7] uv $((uv --version) -replace 'uv ', '')"

# -Verify: just re-run the self-test against an existing venv
if ($Verify) {
    if (-not (Test-Path $VPy)) { throw "No .venv found. Run without -Verify first." }
    & $VPy scripts\selftest.py --server
    exit $LASTEXITCODE
}

# 2) Python 3.12 (managed standalone build - no system Python required)
Write-Host "[2/7] Provisioning Python 3.12 ..."
uv python install 3.12

# 3) virtual environment. Reuse an existing one so a RE-RUN (e.g. installing a bugfix update) does
# not wipe the venv and reinstall every wheel - uv pip install below is idempotent and only touches
# what changed. `uv venv` would recreate the env from scratch. (To switch CPU<->GPU on an existing
# install use install\enable_gpu.ps1, which force-reinstalls just the llama.cpp wheel.)
if (Test-Path $VPy) {
    Write-Host "[3/7] Reusing existing .venv (re-run: nothing re-downloaded that is already present)"
} else {
    Write-Host "[3/7] Creating .venv ..."
    uv venv --python 3.12 .venv
}

# 4) compiler-free heavy wheels FIRST (prebuilt; no toolchain), then the app
if ($UseGpu) {
    Write-Host "[4/7] NVIDIA GPU detected ($Gpu) - installing the CUDA llama.cpp build for GPU offload ..." -ForegroundColor Green
} else {
    Write-Host "[4/7] Installing dependencies (prebuilt CPU wheels - no compiler) ..."
}
uv pip install --python $VPy $LlamaSpec --extra-index-url $LlamaIndex --index-strategy unsafe-best-match
if ($UseGpu) { Add-CudaRuntimeDlls }   # the CUDA wheel needs cudart/cublas beside it or it won't load
uv pip install --python $VPy torch --index-url https://download.pytorch.org/whl/cpu
# research + crawl: web search, article extraction, PDF/arXiv/Wikipedia reading. These were
# omitted, so a bootstrap install came up with the web-facing tools permanently degraded -
# the README advertises "can browse the web" and the tool then reported a missing library.
# Pure-Python/small wheels, no compiler. (playwright still needs `playwright install chromium`
# for real browser automation - see README.)
uv pip install --python $VPy -e ".[cpu,llm,research,crawl]"

# 4b) Playwright browser binary. The `crawl` extra installs the playwright PACKAGE but not the
# Chromium it drives, so browser tools would fail on first use with "install chromium". Fetch it now
# while we know we're online. Non-fatal: browser automation is optional; if this fails the browser
# tools stay unavailable and everything else still works. Run BARE (no 2>&1/|Out-Null) and inside
# try/catch — under PowerShell 5.1 + ErrorActionPreference=Stop, redirecting a native command's
# stderr aborts the whole script (the same trap that broke the CUDA step).
try {
    Write-Host "==> Installing Playwright Chromium (browser automation) ..."
    & $VPy -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Playwright Chromium not installed (exit $LASTEXITCODE). Browser tools stay off until you run: .venv\Scripts\python.exe -m playwright install chromium"
    }
} catch {
    Write-Warning "Playwright browser install skipped: $_"
}

# 5) detect hardware -> provision the best coding kit + write config
if ($SkipModel) {
    Write-Host "[5/7] Skipping model download (-SkipModel). Later: .\.venv\Scripts\python.exe agent\install\provision_model.py"
} else {
    Write-Host "[5/7] Detecting hardware and provisioning a model ($Prefer) ..."
    Push-Location agent
    & "..\.venv\Scripts\python.exe" install\provision_model.py --prefer $Prefer --skip-embedder
    Pop-Location
}

# 6) embedding model - fetched HERE, at install time, while we know the machine is online.
# It used to be downloaded from HuggingFace on FIRST USE, so anyone who installed and then went
# offline (the advertised way to run Layla) silently got keyword-only search forever. Non-fatal:
# a failure warns and continues, because everything else above is already installed and works.
Write-Host "[6/7] Fetching the embedding model (offline semantic search) ..."
Push-Location agent
& "..\.venv\Scripts\python.exe" install\provision_model.py --embedder-only
$EmbedCode = $LASTEXITCODE
Pop-Location
if ($EmbedCode -ne 0) {
    Write-Host "  Embedding model not installed - semantic search will use KEYWORD-ONLY matching." -ForegroundColor Yellow
    Write-Host "  Fix later (needs internet): .\.venv\Scripts\python.exe agent\install\provision_model.py --embedder-only" -ForegroundColor Yellow
}

# 7) deep self-test - prove the model loads + completes a real turn (SIGILL/OOM/corrupt gate)
if (-not $SkipModel) {
    Write-Host "[7/7] Deep self-test (model load + real inference turn) ..." -ForegroundColor Cyan
    $fellBackToCpu = $false
    & $VPy scripts\selftest.py
    if ($LASTEXITCODE -ne 0) {
        # A failed self-test on the CUDA build almost always means the NVIDIA driver is too old or a
        # runtime DLL is missing. Fall back to the CPU wheel (which always loads) so the install still
        # succeeds, and set n_gpu_layers=0 so the config honestly reflects CPU-only inference.
        $retryIndex = $LlamaIndex
        if ($UseGpu) {
            Write-Host "  Self-test failed with the CUDA build - the NVIDIA driver may be too old or a runtime DLL is missing." -ForegroundColor Yellow
            Write-Host "  Falling back to the CPU build so Layla still runs (update your NVIDIA driver, then re-run to get GPU speed) ..." -ForegroundColor Yellow
            $retryIndex = $LlamaIndexCpu
            $fellBackToCpu = $true
            & $VPy -c "import json,pathlib; p=pathlib.Path('agent/runtime_config.json'); d=json.loads(p.read_text('utf-8')) if p.exists() else {}; d['n_gpu_layers']=0; p.write_text(json.dumps(d,indent=2),encoding='utf-8')" 2>$null
        } else {
            Write-Host "  Self-test failed. Reinstalling the llama-cpp CPU wheel and retrying ..." -ForegroundColor Yellow
        }
        uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $retryIndex --index-strategy unsafe-best-match
        & $VPy scripts\selftest.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Self-test still failing. See the [FAIL] lines above. Try -Prefer lite or free more RAM." -ForegroundColor Red
            exit 1
        }
    }
    if ($UseGpu -and -not $fellBackToCpu) {
        Write-Host "  Self-test passed - Layla loads the model on your NVIDIA GPU ($Gpu) and completes a turn." -ForegroundColor Green
    } elseif ($fellBackToCpu) {
        Write-Host "  Self-test passed - Layla runs on CPU. The CUDA build could not load, so GPU offload is OFF." -ForegroundColor Yellow
        Write-Host "  To get GPU speed: update your NVIDIA driver, then re-run  install\enable_gpu.ps1" -ForegroundColor Yellow
    } else {
        Write-Host "  Self-test passed - Layla loads a model and completes a turn on this machine." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "  Done. Layla is installed." -ForegroundColor Green
Write-Host "  Start anytime:     START.bat   (or .\layla.cmd)"
Write-Host "  Re-check anytime:  powershell -File install\bootstrap.ps1 -Verify"
Write-Host ""

# The README tells a non-technical user "when it finishes it opens ... in your browser." That was a
# lie: bootstrap only PRINTED how to start, and INSTALL.bat has no pause, so the console vanished on
# this line after a 10-40 minute download - no app, no browser, no instruction. In -Verify mode we
# do NOT launch (it is a re-check, not a first run). Otherwise, actually start Layla so the promise
# is true, unless the caller opts out (-NoStart, used by CI/automation).
if (-not $Verify -and -not $NoStart) {
    $startBat = Join-Path $PSScriptRoot "..\START.bat"
    if (Test-Path $startBat) {
        Write-Host "  Starting Layla - your browser will open at http://127.0.0.1:8000/ui ..." -ForegroundColor Cyan
        Start-Process -FilePath $startBat -WorkingDirectory (Split-Path $startBat -Parent)
    } else {
        Write-Host "  (START.bat not found - run it yourself to open Layla.)" -ForegroundColor Yellow
        Read-Host "  Press Enter to close"
    }
}
