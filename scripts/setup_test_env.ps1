# Layla — set up a lightweight test environment (Windows / PowerShell).
#
# Creates a Python 3.11/3.12 venv (.venv-test) and installs ONLY the deps needed
# to run the pytest suite — no llama-cpp-python / torch / chromadb build. This is
# the fast path for contributors and for verifying changes without a GPU/model.
#
# Usage:   powershell -ExecutionPolicy Bypass -File scripts\setup_test_env.ps1
# Then:    .\.venv-test\Scripts\Activate.ps1 ; cd agent ; pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host ""
Write-Host "  Layla — test environment setup" -ForegroundColor Cyan
Write-Host "  ------------------------------------------"

# 1. Find a Python 3.11/3.12 interpreter (prefer the py launcher).
function Get-Py312 {
    foreach ($args in @(@("py", "-3.12"), @("py", "-3.11"))) {
        try {
            $v = & $args[0] $args[1] -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and ($v -eq "3.11" -or $v -eq "3.12")) { return $args }
        } catch {}
    }
    # Fall back to a bare `python` only if it is 3.11/3.12.
    try {
        $v = python -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and ($v -eq "3.11" -or $v -eq "3.12")) { return @("python") }
    } catch {}
    return $null
}

$py = Get-Py312
if (-not $py) {
    Write-Host ""
    Write-Host "  [!] No Python 3.11 or 3.12 found." -ForegroundColor Red
    Write-Host "      Install 3.12 from https://www.python.org/downloads/ (check 'Add to PATH')."
    Write-Host "      This machine's default 'python' may be 3.13+, which the dep stack does not support yet."
    exit 1
}
Write-Host "  [1/3]  Using interpreter: $($py -join ' ')"

# 2. Create the test venv.
if (Test-Path ".venv-test\Scripts\python.exe") {
    Write-Host "  [2/3]  .venv-test already exists, reusing."
} else {
    Write-Host "  [2/3]  Creating .venv-test ..."
    & $py[0] $py[1] -m venv .venv-test
}
$venvPy = ".\.venv-test\Scripts\python.exe"

# 3. Install the lightweight test stack (the 'dev' extra).
Write-Host "  [3/3]  Installing test deps (pyproject [dev] extra) ..."
& $venvPy -m pip install -q --upgrade pip
& $venvPy -m pip install -q -e ".[dev]"

Write-Host ""
Write-Host "  Done. Smoke-testing the dependency-free tests..." -ForegroundColor Green
Push-Location agent
& $venvPy -m pytest tests\test_port_guard.py tests\test_url_guard.py tests\test_sandbox_core.py -q
Pop-Location

Write-Host ""
Write-Host "  Run the full (non-heavy) suite with:" -ForegroundColor Cyan
Write-Host "    .\.venv-test\Scripts\Activate.ps1"
Write-Host "    cd agent"
Write-Host "    pytest -m `"not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke`""
