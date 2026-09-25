<#
  clean_install_test.ps1 - install the BUILT installer on a fresh Windows VM and drive the real first-run
  path a new user takes, end to end. Release gate: a failure blocks publishing.

  packaged_smoke.ps1 runs the payload on the BUILD machine (git, Python, the repo checkout all present).
  Every bug a friend hit on a new PC lived in the gap between that and a clean box: the isolated
  embeddable-Python boot crash, the literal "~" models folder, the BOM'd config that fell back to
  "your-model.gguf" ("Service temporarily unavailable"). So this runs on a SEPARATE runner with no repo and
  no Python on PATH, uses the installer silently, launches the INSTALLED layla.exe with no env overrides
  (default %LOCALAPPDATA%\Layla data dir, exactly like a double-click), then:
    1. /health 200
    2. /setup_status says no model yet            (truly fresh)
    3. /setup/download pulls a tiny real GGUF     (the UI's own first-run download route)
    4. /setup_status says the model is ready, under %LOCALAPPDATA%\Layla, no literal "~"
    5. POST /agent returns a real model reply     (not no_model / error / empty)

  Honest limits: a GitHub runner is Windows Server with an admin user, not Windows 11 Home; it has no GPU.

  ASCII-only on purpose (Windows PowerShell 5.1 reads a no-BOM file as ANSI).
  Usage:  ./clean_install_test.ps1 -Installer path\Layla-Setup-X.Y.Z.exe [-Port 8211]
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Installer,
  [int]$Port = 8211,
  [string]$ModelUrl = "https://huggingface.co/bartowski/SmolLM2-360M-Instruct-GGUF/resolve/main/SmolLM2-360M-Instruct-Q4_K_M.gguf",
  [string]$ModelFile = "SmolLM2-360M-Instruct-Q4_K_M.gguf"
)
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:$Port"
$dataDir = Join-Path $env:LOCALAPPDATA "Layla"
$appDir = Join-Path $env:ProgramFiles "Layla"
$script:proc = $null

function Fail([string]$msg) {
  Write-Host "FAIL: $msg"
  foreach ($log in @((Join-Path $dataDir "logs\launch.log"), (Join-Path $dataDir "logs\layla.log"))) {
    if (Test-Path $log) { Write-Host "--- $log (tail) ---"; Get-Content $log -Tail 60 }
  }
  $cfg = Join-Path $dataDir "runtime_config.json"
  if (Test-Path $cfg) { Write-Host "--- runtime_config.json ---"; Get-Content $cfg -Raw }
  if ($script:proc -and -not $script:proc.HasExited) { Stop-Process -Id $script:proc.Id -Force -ErrorAction SilentlyContinue }
  exit 1
}

function Get-Json([string]$path, [int]$timeout = 30) {
  return (Invoke-WebRequest "$base$path" -UseBasicParsing -TimeoutSec $timeout).Content | ConvertFrom-Json
}

# --- 0. Make this box look like a PC that has never seen Python or Layla ---------------------------------
$env:Path = (($env:Path -split ";") | Where-Object { $_ -and ($_ -notmatch "(?i)python") }) -join ";"
foreach ($v in @("LAYLA_DATA_DIR", "LAYLA_INSTALL_ROOT", "PYTHONPATH", "PYTHONHOME")) { Remove-Item "Env:$v" -ErrorAction SilentlyContinue }
$env:LAYLA_NO_DIALOG = "1"   # an error MessageBox would hang a headless runner; the text still goes to launch.log
$pyOnPath = Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch "WindowsApps" }
if ($pyOnPath) { Fail "PROBE BROKEN: python still on PATH ($($pyOnPath.Source)) - not a clean-machine test" }
if (Test-Path $dataDir) { Fail "PROBE BROKEN: $dataDir already exists - not a fresh profile" }
if (-not (Test-Path $Installer)) { Fail "installer not found: $Installer" }
Write-Host "==> clean box: no python on PATH, no $dataDir"

# --- 1. Silent install, exactly the shipped .exe ---------------------------------------------------------
$instLog = Join-Path $env:TEMP "layla_install.log"
Write-Host "==> installing $Installer"
$p = Start-Process -FilePath $Installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/LOG=$instLog") -Wait -PassThru
if ($p.ExitCode -ne 0) { if (Test-Path $instLog) { Get-Content $instLog -Tail 40 }; Fail "installer exit code $($p.ExitCode)" }
$exe = Join-Path $appDir "layla.exe"
if (-not (Test-Path $exe)) { Fail "installed layla.exe missing at $exe" }
Write-Host "   OK installed to $appDir"

# --- 2. Launch the INSTALLED app the way the Start-menu shortcut does -----------------------------------
Write-Host "==> launching installed layla.exe"
$script:proc = Start-Process -FilePath $exe -ArgumentList @("--port", "$Port", "--no-tray") -WorkingDirectory $appDir -PassThru -WindowStyle Hidden
$healthy = $false
for ($i = 0; $i -lt 180; $i++) {
  Start-Sleep -Seconds 1
  try { if ((Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $healthy = $true; break } } catch { }
  if ($script:proc.HasExited) { break }
}
if (-not $healthy) { Fail "engine never became healthy on a clean install" }
Write-Host "   OK /health 200"

# --- 3. Fresh: no model yet -----------------------------------------------------------------------------
$st = Get-Json "/setup_status"
if ($st.model_found) { Fail "PROBE BROKEN: a fresh install already reports a model ($($st | ConvertTo-Json -Compress))" }
Write-Host "   OK /setup_status: no model yet (fresh)"

# --- 4. First-run model download through the UI's own route ---------------------------------------------
Write-Host "==> first-run download via /setup/download ($ModelFile)"
$q = "/setup/download?url=" + [uri]::EscapeDataString($ModelUrl) + "&filename=" + [uri]::EscapeDataString($ModelFile)
$sse = (Invoke-WebRequest "$base$q" -UseBasicParsing -TimeoutSec 1200).Content
$errLine = ($sse -split "`n") | Where-Object { $_ -match '"error"' } | Select-Object -First 1
if ($errLine) { Fail "download reported: $errLine" }
if ($sse -notmatch '"done":\s*true') { Fail "download stream ended without done=true. Tail: $($sse.Substring([Math]::Max(0, $sse.Length - 400)))" }
Write-Host "   OK download finished"

$st = Get-Json "/setup_status"
if (-not $st.model_found) { Fail "model downloaded but /setup_status still says no model: $($st | ConvertTo-Json -Compress)" }
$gguf = Get-ChildItem -Path $dataDir -Recurse -Filter $ModelFile -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gguf) { Fail "$ModelFile not found under $dataDir" }
if ($gguf.FullName -match "\\~\\|\\~$") { Fail "model landed in a literal '~' folder: $($gguf.FullName)" }
$cfgText = Get-Content (Join-Path $dataDir "runtime_config.json") -Raw
if ($cfgText -notmatch [regex]::Escape($ModelFile)) { Fail "runtime_config.json does not name the downloaded model" }
Write-Host "   OK model ready at $($gguf.FullName)"

# --- 5. A real reply from the real model ----------------------------------------------------------------
Write-Host "==> POST /agent (real model turn)"
$body = @{ message = "Say hello in one short sentence."; stream = $false } | ConvertTo-Json
try {
  $r = Invoke-WebRequest "$base/agent" -Method Post -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 600
} catch {
  $detail = ""
  if ($_.Exception.Response) { try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { } }
  Fail "/agent request failed: $($_.Exception.Message) $detail"
}
$d = $r.Content | ConvertFrom-Json
$status = "" + $d.state.status
$reply = ("" + $d.response).Trim()
Write-Host "   status=$status reply=[$reply]"
if ($d.error) { Fail "/agent returned error=$($d.error)" }
if ($status -in @("no_model", "error", "system_busy", "timeout")) { Fail "/agent turn status=$status" }
if ($reply.Length -lt 2) { Fail "/agent returned an empty reply" }
if ($reply -match "(?i)temporarily unavailable|no model") { Fail "/agent reply is a service/no-model message, not a model answer" }
Write-Host "   OK real reply"

if ($script:proc -and -not $script:proc.HasExited) { Stop-Process -Id $script:proc.Id -Force -ErrorAction SilentlyContinue }
Write-Host "==> CLEAN INSTALL TEST PASSED"
