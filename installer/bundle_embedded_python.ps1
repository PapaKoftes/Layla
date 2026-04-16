# Optional: bundle Python 3.12 embeddable + pip into installer payload for zero-prereq installs.
# Run from repo root after payload exists:
#   .\installer\bundle_embedded_python.ps1 -PayloadDir .\installer\payload\Layla
#
# Requires: PowerShell 5+, internet. Edits python312._pth to enable site-packages.
# If download fails, script exits 0 with a warning (CI-friendly).

param(
  [string]$PayloadDir = "",
  # Default to 3.12 (embeddable distribution is available; matches supported runtime).
  [string]$PythonVersion = "3.12.10"
)

$ErrorActionPreference = "Stop"
if (-not $PayloadDir) {
  $PayloadDir = Join-Path $PSScriptRoot "payload\Layla"
}
$PyRoot = Join-Path $PayloadDir "python"
if (-not (Test-Path $PayloadDir)) {
  Write-Warning "PayloadDir not found: $PayloadDir - skip embedded Python bundle."
  exit 0
}

$zipName = "python-$PythonVersion-embed-amd64.zip"
$url = "https://www.python.org/ftp/python/$PythonVersion/$zipName"
$null = New-Item -ItemType Directory -Force -Path $PyRoot
$zipPath = Join-Path $env:TEMP $zipName

$download_ok = $true
try {
  Write-Host "==> Downloading embeddable Python $PythonVersion"
  Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
  Expand-Archive -Path $zipPath -DestinationPath $PyRoot -Force
} catch {
  $download_ok = $false
  Write-Warning "Embedded Python download/extract failed: $_ - build continues without bundle."
}
if (Test-Path $zipPath) { Remove-Item $zipPath -Force -ErrorAction SilentlyContinue }
if (-not $download_ok) { exit 0 }

$pth = Get-ChildItem -Path $PyRoot -Filter "python*._pth" | Select-Object -First 1
if ($pth) {
  $lines = Get-Content $pth.FullName
  $out = @()
  foreach ($line in $lines) {
    if ($line -match '^\s*#\s*import site') { $out += 'import site' }
    elseif ($line -eq 'import site') { $out += 'import site' }
    else { $out += $line }
  }
  if ($out -notcontains 'import site') { $out += 'import site' }
  Set-Content -Path $pth.FullName -Value ($out -join "`r`n") -Encoding ASCII
}

$pyExe = Join-Path $PyRoot "python.exe"
if (-not (Test-Path $pyExe)) {
  Write-Warning "python.exe missing after extract."
  exit 0
}

Write-Host "==> Bootstrap pip (get-pip)"
$getPip = Join-Path $env:TEMP "get-pip.py"
try {
  Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
  & $pyExe $getPip --no-warn-script-location --disable-pip-version-check
} catch {
  Write-Warning "get-pip failed: $_"
}
if (Test-Path $getPip) { Remove-Item $getPip -Force -ErrorAction SilentlyContinue }

Write-Host "==> pip install Layla requirements (may take several minutes)"
$req = Join-Path $PayloadDir "agent\requirements.txt"
if (Test-Path $req) {
  try {
    # llama-cpp-python is the most failure-prone dependency (native build toolchain).
    # Prefer a prebuilt wheel; if none is available, warn and continue so the payload can still be built.
    & $pyExe -m pip install scikit-build-core --no-warn-script-location --disable-pip-version-check --no-cache-dir
    & $pyExe -m pip install "llama-cpp-python>=0.3.1,<0.4" --only-binary=:all: --no-warn-script-location --disable-pip-version-check --no-cache-dir

    $tmpReq = Join-Path $env:TEMP ("layla_requirements_no_llama_" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
      $lines = Get-Content -Path $req
      $filtered = @()
      foreach ($line in $lines) {
        if ($line -match '^\s*llama-cpp-python\b') { continue }
        $filtered += $line
      }
      Set-Content -Path $tmpReq -Value ($filtered -join "`r`n") -Encoding UTF8
      & $pyExe -m pip install -r $tmpReq --no-warn-script-location --disable-pip-version-check --no-cache-dir
    } finally {
      if (Test-Path $tmpReq) { Remove-Item $tmpReq -Force -ErrorAction SilentlyContinue }
    }
  } catch {
    Write-Warning "pip install -r requirements failed: $_"
  }
} else {
  Write-Warning "requirements.txt not found at $req"
}

Write-Host "Embedded Python bundle complete under $PyRoot"
