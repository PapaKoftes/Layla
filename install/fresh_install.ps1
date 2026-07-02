# Layla - fresh, compiler-free install (Windows / PowerShell).
#
# One command on a clean laptop: installs Python 3.12 if needed, builds a venv,
# installs the COMPILER-FREE dependency set (llama-cpp + torch CPU wheels, no C++
# toolchain), detects the hardware and downloads the best coding model + kit, then
# runs a DEEP SELF-TEST that proves the model actually loads and completes a real
# turn (so an AVX-512 SIGILL or a corrupt model is caught at install, not on first
# use). Finally it can guide you through pairing with your other Layla install.
#
#   git clone https://github.com/PapaKoftes/Layla.git
#   cd Layla
#   powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI when
# there is no BOM, so non-ASCII punctuation (em-dash, box-drawing) breaks parsing.
#
# Options:
#   -Prefer quality|balanced|lite|speed   model bias for the detected hardware (default balanced)
#   -SkipModel                            set up the env but don't download the model yet
#   -Spanish / -LanguageHelper / -Aspects "morrigan,nyx"   Castilla / multi-aspect kit options
#   -Verify    skip install; just run the deep self-test (re-runnable doctor) against an existing .venv
#   -Pair      after install, launch the guided "pair with my other PC" wizard
param(
    [ValidateSet("quality", "balanced", "lite", "speed")][string]$Prefer = "balanced",
    [switch]$SkipModel,
    [switch]$Spanish,
    [switch]$LanguageHelper,
    [string]$Aspects = "",
    [switch]$Verify,
    [switch]$Pair
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot          # install\ -> repo root
Set-Location $Repo

Write-Host ""
Write-Host "  Layla - fresh install (compiler-free)" -ForegroundColor Magenta
Write-Host "  -------------------------------------"

function Find-Py312 {
    # The py launcher selects the exact version for -3.12 / -3.11; a clean exit means
    # that interpreter exists. No version-string parsing (avoids arg/quoting pitfalls).
    foreach ($v in @("3.12", "3.11")) {
        try {
            & py "-$v" -c "import sys" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return @("py", "-$v") }
        } catch {}
    }
    return $null
}

$VPy = ".\.venv\Scripts\python.exe"

# -Verify: just run the self-test against the existing venv and exit
if ($Verify) {
    if (-not (Test-Path $VPy)) { throw "No .venv found. Run the installer first (without -Verify)." }
    Write-Host "Running deep self-test (server mode) ..." -ForegroundColor Cyan
    & $VPy scripts\selftest.py --server
    exit $LASTEXITCODE
}

# 1) Python 3.12
$py = Find-Py312
if (-not $py) {
    Write-Host "[1/6] Installing Python 3.12 (winget, user scope)..."
    winget install --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --silent
    $py = Find-Py312
    if (-not $py) { throw "Python 3.12 not found after install. Install from https://python.org (add to PATH) and re-run." }
}
Write-Host "[1/6] Python interpreter: $($py -join ' ')"

# 2) venv
if (-not (Test-Path $VPy)) {
    Write-Host "[2/6] Creating .venv ..."
    & $py[0] $py[1] -m venv .venv
} else {
    Write-Host "[2/6] Reusing existing .venv"
}
& $VPy -m pip install -q --upgrade pip

# 3) compiler-free heavy wheels FIRST (prebuilt; no toolchain)
Write-Host "[3/6] Installing llama-cpp (CPU wheel) + torch (CPU wheel) ..."
& $VPy -m pip install "llama-cpp-python>=0.3.1,<0.4" `
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu `
    --only-binary llama-cpp-python --prefer-binary
& $VPy -m pip install torch --index-url https://download.pytorch.org/whl/cpu --only-binary :all:

# 4) the app, compiler-free extra (cpu = core minus chromadb) + llm
Write-Host "[4/6] Installing Layla ([cpu,llm] extras) ..."
& $VPy -m pip install -e ".[cpu,llm]" --prefer-binary

# 5) detect hardware -> provision the best coding kit + write config
if ($SkipModel) {
    Write-Host "[5/6] Skipping model download (-SkipModel). Run later: .venv\Scripts\python.exe agent\install\provision_model.py"
} else {
    Write-Host "[5/6] Detecting hardware and provisioning the best coding kit ($Prefer) ..."
    Push-Location agent
    $provArgs = @("install\provision_model.py", "--prefer", $Prefer)
    if ($Spanish) { $provArgs += "--spanish" }
    if ($LanguageHelper) { $provArgs += "--language-assist" }
    if ($Aspects) { $provArgs += @("--aspects", $Aspects) }
    & "..\.venv\Scripts\python.exe" @provArgs
    Pop-Location
}

# 6) DEEP SELF-TEST - prove the model loads + completes a real turn (SIGILL/OOM/corrupt-GGUF gate)
if (-not $SkipModel) {
    Write-Host "[6/6] Deep self-test (model load + real inference turn) ..." -ForegroundColor Cyan
    & $VPy scripts\selftest.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  Self-test failed. Attempting recovery: reinstalling the llama-cpp CPU wheel" -ForegroundColor Yellow
        Write-Host "  (handles a corrupt wheel or an AVX-512 build this CPU can't run) ..."
        & $VPy -m pip install --force-reinstall --no-cache-dir "llama-cpp-python>=0.3.1,<0.4" `
            --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu `
            --only-binary llama-cpp-python --prefer-binary
        & $VPy scripts\selftest.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "  Self-test still failing. See the [FAIL] lines above for the exact cause." -ForegroundColor Red
            Write-Host "  Common fixes: a smaller model (re-run with -Prefer lite), more free RAM, or a" -ForegroundColor Red
            Write-Host "  llama-cpp wheel matching this CPU. The install is otherwise complete." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Self-test passed - Layla loads a model and completes a turn on this machine." -ForegroundColor Green
}

Write-Host ""
Write-Host "  Done. To start Layla:" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    cd agent ; python serve.py        # then open http://127.0.0.1:8000/ui"
Write-Host ""
Write-Host "  Re-check anytime:  powershell -File install\fresh_install.ps1 -Verify"

# 7) optional guided pairing with the other PC
if ($Pair) {
    Write-Host ""
    Write-Host "  Launching the guided pairing wizard ..." -ForegroundColor Cyan
    & $VPy scripts\pair.py
} else {
    Write-Host "  Pair with your other PC:  .\.venv\Scripts\python.exe scripts\pair.py"
}
Write-Host ""
