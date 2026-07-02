# Layla - DEPRECATED installer shim.
#
# The old root installer compiled llama-cpp/chromadb (needs a C++ toolchain) and selected
# Python via bare `python` — which is 3.14 on many machines and unsupported. It is retired
# in favor of the compiler-free, self-test-gated installer. This shim just forwards to it.
param([Parameter(ValueFromRemainingArguments = $true)]$Rest)
$ErrorActionPreference = "Stop"
Write-Host ""
Write-Host "  [deprecated] Root install.ps1 required a C++ toolchain and bare 'python' (often 3.14)." -ForegroundColor Yellow
Write-Host "  Using the supported compiler-free installer instead: install\fresh_install.ps1" -ForegroundColor Yellow
Write-Host ""
$target = Join-Path $PSScriptRoot "install\fresh_install.ps1"
if (-not (Test-Path $target)) { throw "install\fresh_install.ps1 not found next to this shim." }
& $target @Rest
