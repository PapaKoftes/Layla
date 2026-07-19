# Layla - one-command installer (Windows / PowerShell) powered by uv.
#
# Installs Python ITSELF + every dependency, then provisions a model for your
# hardware and runs a deep self-test. No system Python, no MSVC/CMake, no admin:
# uv fetches a standalone Python and we install prebuilt CPU wheels for llama-cpp
# + torch, so there is nothing to compile.
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
#   -SkipModel                            set up the env but don't download a model yet
#   -Verify                               skip install; just run the deep self-test
param(
    [ValidateSet("quality", "balanced", "lite", "speed")][string]$Prefer = "balanced",
    [switch]$SkipModel,
    [switch]$Verify
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot          # install\ -> repo root
Set-Location $Repo

Write-Host ""
Write-Host "  Layla - installer (uv, compiler-free)" -ForegroundColor Magenta
Write-Host "  -------------------------------------"

$LlamaIndex = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
$LlamaSpec = "llama-cpp-python>=0.3.1,<0.4"
$VPy = ".\.venv\Scripts\python.exe"

function Test-Uv {
    try { uv --version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

# 1) ensure uv (single static binary; needs no Python, no admin)
if (-not (Test-Uv)) {
    Write-Host "[1/6] Installing uv (Astral) ..."
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Test-Uv)) {
    throw "uv is installed but not on PATH. Open a NEW terminal and re-run install\bootstrap.ps1."
}
Write-Host "[1/6] uv $((uv --version) -replace 'uv ', '')"

# -Verify: just re-run the self-test against an existing venv
if ($Verify) {
    if (-not (Test-Path $VPy)) { throw "No .venv found. Run without -Verify first." }
    & $VPy scripts\selftest.py --server
    exit $LASTEXITCODE
}

# 2) Python 3.12 (managed standalone build - no system Python required)
Write-Host "[2/6] Provisioning Python 3.12 ..."
uv python install 3.12

# 3) virtual environment
Write-Host "[3/6] Creating .venv ..."
uv venv --python 3.12 .venv

# 4) compiler-free heavy wheels FIRST (prebuilt; no toolchain), then the app
Write-Host "[4/6] Installing dependencies (prebuilt CPU wheels - no compiler) ..."
uv pip install --python $VPy $LlamaSpec --extra-index-url $LlamaIndex --index-strategy unsafe-best-match
uv pip install --python $VPy torch --index-url https://download.pytorch.org/whl/cpu
# research + crawl: web search, article extraction, PDF/arXiv/Wikipedia reading. These were
# omitted, so a bootstrap install came up with the web-facing tools permanently degraded —
# the README advertises "can browse the web" and the tool then reported a missing library.
# Pure-Python/small wheels, no compiler. (playwright still needs `playwright install chromium`
# for real browser automation — see README.)
uv pip install --python $VPy -e ".[cpu,llm,research,crawl]"

# 5) detect hardware -> provision the best coding kit + write config
if ($SkipModel) {
    Write-Host "[5/6] Skipping model download (-SkipModel). Later: .\.venv\Scripts\python.exe agent\install\provision_model.py"
} else {
    Write-Host "[5/6] Detecting hardware and provisioning a model ($Prefer) ..."
    Push-Location agent
    & "..\.venv\Scripts\python.exe" install\provision_model.py --prefer $Prefer
    Pop-Location
}

# 6) deep self-test - prove the model loads + completes a real turn (SIGILL/OOM/corrupt gate)
if (-not $SkipModel) {
    Write-Host "[6/6] Deep self-test (model load + real inference turn) ..." -ForegroundColor Cyan
    & $VPy scripts\selftest.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Self-test failed. Reinstalling the llama-cpp CPU wheel and retrying ..." -ForegroundColor Yellow
        uv pip install --python $VPy --reinstall $LlamaSpec --extra-index-url $LlamaIndex --index-strategy unsafe-best-match
        & $VPy scripts\selftest.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Self-test still failing. See the [FAIL] lines above. Try -Prefer lite or free more RAM." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Self-test passed - Layla loads a model and completes a turn on this machine." -ForegroundColor Green
}

Write-Host ""
Write-Host "  Done. Start Layla:  .\layla.cmd   (or: .venv\Scripts\python.exe agent\serve.py)" -ForegroundColor Green
Write-Host "  Layla opens at http://127.0.0.1:8000/ui"
Write-Host "  Re-check anytime:  powershell -File install\bootstrap.ps1 -Verify"
Write-Host ""
