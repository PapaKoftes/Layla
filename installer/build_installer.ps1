# Build Layla Windows installer payload + compile Inno Setup script.
# Run from repo root in PowerShell:
#   .\installer\build_installer.ps1
#
# Requires: Python 3.11+ on PATH, pip, PyInstaller (`pip install pyinstaller`),
#           Inno Setup 6+ (iscc.exe on PATH) for the final .exe installer.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Payload = Join-Path $PSScriptRoot "payload\Layla"
$null = New-Item -ItemType Directory -Force -Path $Payload

Write-Host "==> Sync agent + launcher assets into payload"
Copy-Item -Path (Join-Path $Root "agent") -Destination $Payload -Recurse -Force
Copy-Item -Path (Join-Path $Root "personalities") -Destination $Payload -Recurse -Force -ErrorAction SilentlyContinue
foreach ($f in @("MODELS.md", "VALUES.md", "README.md")) {
  $src = Join-Path $Root $f
  if (Test-Path $src) { Copy-Item $src $Payload -Force }
}
Copy-Item -Path (Join-Path $Root "agent\runtime_config.example.json") -Destination (Join-Path $Payload "runtime_config.example.json") -Force

Write-Host "==> Build layla.exe with PyInstaller"
Push-Location $Root
try {
  python -m pip install pyinstaller --quiet
  python -m PyInstaller launcher\layla.spec --noconfirm
  $exe = Join-Path $Root "dist\layla.exe"
  if (-not (Test-Path $exe)) { throw "PyInstaller did not produce dist\layla.exe" }
  Copy-Item $exe (Join-Path $Payload "layla.exe") -Force
}
finally { Pop-Location }

# Optional embedded Python (zero local Python prereq for end users). Set env LAYLA_BUNDLE_EMBEDDED_PYTHON=1
if ($env:LAYLA_BUNDLE_EMBEDDED_PYTHON -eq "1") {
  Write-Host "==> Bundling embeddable Python (LAYLA_BUNDLE_EMBEDDED_PYTHON=1)"
  try {
    & (Join-Path $PSScriptRoot "bundle_embedded_python.ps1") -PayloadDir $Payload
  } catch {
    Write-Warning "bundle_embedded_python.ps1 failed: $_"
  }
}

Write-Host "==> Seed user template (optional copy on first run is handled by launcher)"
$dataHint = Join-Path $Payload "DATA_DIR_README.txt"
@"
Per-user data lives under %LOCALAPPDATA%\Layla (set via LAYLA_DATA_DIR):
 runtime_config.json, layla.db, models\, chroma\, logs\

On first launch, copy runtime_config.example.json to that folder as runtime_config.json if missing.
"@ | Set-Content -Path $dataHint -Encoding UTF8

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
  Write-Warning "Inno Setup compiler (iscc.exe) not on PATH — payload ready at $Payload. Install Inno Setup and run: iscc installer\layla.iss"
  exit 0
}

Write-Host "==> Compile installer with Inno Setup"
& iscc (Join-Path $PSScriptRoot "layla.iss")
Write-Host "Done."
