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

function Resolve-PackagingPython {
  # Prefer the Windows Python Launcher when present (common dev machines may have 3.14 as `python`).
  $candidates = @(
    @{ Name = "py -3.12"; Args = @("-3.12", "-c", "import sys; print(sys.executable)") },
    @{ Name = "py -3.11"; Args = @("-3.11", "-c", "import sys; print(sys.executable)") },
    @{ Name = "python"; Args = @("-c", "import sys; print(sys.executable)") }
  )
  foreach ($c in $candidates) {
    try {
      $exe = ""
      if ($c.Name -like "py *") {
        $exe = (& py @($c.Args) | Select-Object -First 1).Trim()
      } else {
        $exe = (& python @($c.Args) | Select-Object -First 1).Trim()
      }
      if ($exe -and (Test-Path $exe)) { return [pscustomobject]@{ Exe = $exe; Source = $c.Name } }
    } catch {
      # try next
    }
  }
  return $null
}

$pyPick = Resolve-PackagingPython
if (-not $pyPick) {
  throw "Could not find a Python interpreter on PATH. Install Python 3.11 or 3.12 and retry."
}
$PythonExe = $pyPick.Exe
Write-Host ("==> Packaging Python: {0} ({1})" -f $PythonExe, $pyPick.Source)

$pyMajorMinor = ""
try {
  $pyMajorMinor = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" | Select-Object -First 1).Trim()
} catch {
  $pyMajorMinor = ""
}
if ($pyMajorMinor -notin @("3.11", "3.12")) {
  if ($env:LAYLA_ALLOW_PACKAGING_ON_UNSUPPORTED_PYTHON -in @("1", "true", "yes")) {
    Write-Warning "Unsupported Python $pyMajorMinor for packaging; continuing because LAYLA_ALLOW_PACKAGING_ON_UNSUPPORTED_PYTHON is set."
  } else {
    throw @"
Unsupported Python for Windows installer build: $pyMajorMinor

Layla supports Python 3.11–3.12 for reliable PyInstaller + dependency resolution.
Fix:
  - Install Python 3.12 (recommended) and ensure `py -3.12` works, OR
  - Put Python 3.11/3.12 earlier on PATH than newer interpreters.

Emergency escape hatch (not recommended):
  - set LAYLA_ALLOW_PACKAGING_ON_UNSUPPORTED_PYTHON=1
"@
  }
}

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
  & $PythonExe -m pip install pyinstaller --quiet
  & $PythonExe -m PyInstaller launcher\layla.spec --noconfirm
  $exe = Join-Path $Root "dist\layla.exe"
  if (-not (Test-Path $exe)) { throw "PyInstaller did not produce dist\layla.exe" }
  Copy-Item $exe (Join-Path $Payload "layla.exe") -Force
}
finally { Pop-Location }

# Embedded Python (zero local Python prereq for end users).
# Default: ON. Set env LAYLA_BUNDLE_EMBEDDED_PYTHON=0 to skip.
if ($env:LAYLA_BUNDLE_EMBEDDED_PYTHON -ne "0") {
  Write-Host "==> Bundling embeddable Python (set LAYLA_BUNDLE_EMBEDDED_PYTHON=0 to skip)"
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
  Write-Warning ("Inno Setup compiler (iscc.exe) not on PATH - payload ready at {0}. Install Inno Setup and run: iscc installer\\layla.iss" -f $Payload)
  exit 0
}

Write-Host "==> Compile installer with Inno Setup"
$ver = ""
try {
  $ver = (& $PythonExe -c "import sys; sys.path.insert(0,'agent'); import version; print(version.__version__)" | Select-Object -First 1).Trim()
} catch {
  $ver = ""
}
if (-not $ver) { $ver = "0.0.0" }
& iscc "/DMyAppVersion=$ver" (Join-Path $PSScriptRoot "layla.iss")

try {
  $outDir = Join-Path $PSScriptRoot "output"
  if (Test-Path $outDir) {
    $setup = Join-Path $outDir ("Layla-Setup-" + $ver + ".exe")
    if (Test-Path $setup) {
      $hash = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
      $sumFile = Join-Path $outDir "SHA256SUMS.txt"
      ($hash + "  " + (Split-Path -Leaf $setup)) | Set-Content -Path $sumFile -Encoding ASCII
      Write-Host "==> SHA256: $hash"
    }
  }
} catch {
  Write-Warning "Checksum generation failed: $_"
}
Write-Host "Done."
