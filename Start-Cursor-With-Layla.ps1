# Launch Cursor with Layla fully integrated:
# - Layla server starts in the background (no visible window).
# - Only Cursor is visible. Select "layla" in the model dropdown to use it.
# - When Cursor closes, Layla stops automatically.
#
# Run: powershell -ExecutionPolicy Bypass -File "<repo-root>\Start-Cursor-With-Layla.ps1"
# Or create a shortcut to this script.

$ErrorActionPreference = "Stop"
$RepoRoot     = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$CursorExe    = "$env:LOCALAPPDATA\Programs\Cursor\Cursor.exe"
$AgentDir     = Join-Path $RepoRoot "agent"
$VenvPython   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LaylaUrl     = "http://127.0.0.1:8000/v1/models"
$LaylaLog     = Join-Path $RepoRoot "layla-server.log"

if (-not (Test-Path $CursorExe)) {
    Write-Error "Cursor not found at $CursorExe"
    exit 1
}
if (-not (Test-Path $VenvPython)) {
    # Try legacy venv path too
    $VenvPython = "$AgentDir\venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        Write-Error "Layla venv not found. Run INSTALL.bat first."
        exit 1
    }
}

Write-Host "∴ Starting Layla server (hidden)..."
$laylaProc = Start-Process `
    -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $AgentDir `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardError $LaylaLog

# Wait for server to respond (model load can take 20–60 seconds on first run)
$maxAttempts = 30
$attempt = 0
$ready = $false
Write-Host "  Waiting for Layla to load the model..." -NoNewline
while ($attempt -lt $maxAttempts) {
    Start-Sleep -Seconds 2
    $attempt++
    Write-Host "." -NoNewline
    try {
        $null = Invoke-RestMethod -Uri $LaylaUrl -Method Get -TimeoutSec 4 -ErrorAction Stop
        $ready = $true
        break
    } catch {
        if ($laylaProc.HasExited) {
            Write-Host ""
            Write-Warning "Layla server exited (exit code: $($laylaProc.ExitCode))."
            if (Test-Path $LaylaLog) {
                Write-Host "--- Error log ($LaylaLog) ---"
                Get-Content $LaylaLog -Tail 40
                Write-Host "--- Fix: cd $AgentDir; ..\\.venv\Scripts\Activate.ps1; pip install -r requirements.txt ---"
            } else {
                Write-Host "Diagnose: cd $AgentDir; ..\\.venv\Scripts\Activate.ps1; python -m uvicorn main:app --host 127.0.0.1 --port 8000"
            }
            break
        }
    }
}
Write-Host ""

if ($ready) {
    Write-Host "  Layla is ready. Starting Cursor."
} else {
    if ($laylaProc -and -not $laylaProc.HasExited) {
        Write-Warning "  Model still loading — Cursor will start. Try the layla model in a minute."
    }
}

# Minimize this window so only Cursor is visible
try {
    Add-Type -Name Win -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);' -Namespace Native -ErrorAction SilentlyContinue
    $hwnd = (Get-Process -Id $PID).MainWindowHandle
    if ($hwnd -ne [IntPtr]::Zero) { [Native.Win]::ShowWindow($hwnd, 6) }
} catch { }

Start-Process $CursorExe

# Keep script alive until Cursor closes, then stop Layla
while (Get-Process -Name "Cursor" -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 2
}

if ($laylaProc -and -not $laylaProc.HasExited) {
    $laylaProc.Kill()
    Write-Host "Layla server stopped."
}
