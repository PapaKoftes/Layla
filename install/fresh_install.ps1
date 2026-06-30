# Layla — fresh, compiler-free install (Windows / PowerShell).
#
# One command on a clean laptop: installs Python 3.12 if needed, builds a venv,
# installs the COMPILER-FREE dependency set (llama-cpp + torch CPU wheels, no C++
# toolchain), then detects the hardware and downloads the best coding model + kit.
#
#   git clone https://github.com/PapaKoftes/Layla.git
#   cd Layla
#   powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1
#
# Options:
#   -Prefer quality|balanced|speed   model bias for the detected hardware (default balanced)
#   -SkipModel                       set up the env but don't download the model yet
param(
    [ValidateSet("quality", "balanced", "lite", "speed")][string]$Prefer = "balanced",
    [switch]$SkipModel,
    [switch]$Spanish
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot          # install\ -> repo root
Set-Location $Repo

Write-Host ""
Write-Host "  Layla — fresh install (compiler-free)" -ForegroundColor Magenta
Write-Host "  -------------------------------------"

function Find-Py312 {
    foreach ($v in @("3.12", "3.11")) {
        try {
            $ver = & py "-$v" -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and ($ver -eq "3.12" -or $ver -eq "3.11")) { return @("py", "-$v") }
        } catch {}
    }
    return $null
}

# 1) Python 3.12
$py = Find-Py312
if (-not $py) {
    Write-Host "[1/5] Installing Python 3.12 (winget, user scope)..."
    winget install --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --silent
    $py = Find-Py312
    if (-not $py) { throw "Python 3.12 not found after install. Install from https://python.org (add to PATH) and re-run." }
}
Write-Host "[1/5] Python interpreter: $($py -join ' ')"

# 2) venv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[2/5] Creating .venv ..."
    & $py[0] $py[1] -m venv .venv
} else {
    Write-Host "[2/5] Reusing existing .venv"
}
$VPy = ".\.venv\Scripts\python.exe"
& $VPy -m pip install -q --upgrade pip

# 3) compiler-free heavy wheels FIRST (prebuilt; no toolchain)
Write-Host "[3/5] Installing llama-cpp (CPU wheel) + torch (CPU wheel) ..."
& $VPy -m pip install "llama-cpp-python>=0.3.1,<0.4" `
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu `
    --only-binary llama-cpp-python --prefer-binary
& $VPy -m pip install torch --index-url https://download.pytorch.org/whl/cpu --only-binary :all:

# 4) the app, compiler-free extra (cpu = core minus chromadb) + llm
Write-Host "[4/5] Installing Layla ([cpu,llm] extras) ..."
& $VPy -m pip install -e ".[cpu,llm]" --prefer-binary

# 5) detect hardware -> provision the best coding kit + write config
if ($SkipModel) {
    Write-Host "[5/5] Skipping model download (-SkipModel). Run later: .venv\Scripts\python.exe agent\install\provision_model.py"
} else {
    Write-Host "[5/5] Detecting hardware and provisioning the best coding kit ($Prefer) ..."
    Push-Location agent
    $provArgs = @("install\provision_model.py", "--prefer", $Prefer)
    if ($Spanish) { $provArgs += "--spanish" }
    & "..\.venv\Scripts\python.exe" @provArgs
    Pop-Location
}

Write-Host ""
Write-Host "  Done. To start Layla:" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    cd agent ; python serve.py        # then open http://127.0.0.1:8000"
Write-Host ""
Write-Host "  To connect to your main-PC Layla over a tunnel, see install\INSTALL.md (Connect section)."
Write-Host ""
