# Launch Cursor with Jinx fully integrated:
# - Jinx server starts in the background (no visible window).
# - Only Cursor is visible. Select "Jinx" in the model dropdown to use it.
# - When Cursor closes, Jinx stops automatically.
#
# Run: powershell -ExecutionPolicy Bypass -File "C:\Users\minam\local-jinx-agent\Start-Cursor-With-Jinx.ps1"
# Or create a shortcut to this script.

$ErrorActionPreference = "Stop"
$CursorExe = "$env:LOCALAPPDATA\Programs\Cursor\Cursor.exe"
$AgentDir = "$env:USERPROFILE\local-jinx-agent\agent"
$PythonExe = Join-Path $AgentDir "venv\Scripts\python.exe"
$JinxUrl = "http://127.0.0.1:8000/v1/models"
$JinxLog = "$env:USERPROFILE\local-jinx-agent\jinx-server-error.log"

if (-not (Test-Path $CursorExe)) {
    Write-Error "Cursor not found at $CursorExe"
    exit 1
}
if (-not (Test-Path $PythonExe)) {
    Write-Error "Jinx venv not found at $PythonExe"
    exit 1
}

Write-Host "Starting Jinx server (hidden)..."
# Start Jinx server in a hidden process; capture stderr to log so we can show it on crash
$jinxProc = Start-Process -FilePath $PythonExe -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $AgentDir -WindowStyle Hidden -PassThru -RedirectStandardError $JinxLog

# Wait for server to respond (retry a few times; model load is slow on first request)
$maxAttempts = 15
$attempt = 0
$ready = $false
while ($attempt -lt $maxAttempts) {
    Start-Sleep -Seconds 2
    $attempt++
    try {
        $null = Invoke-RestMethod -Uri $JinxUrl -Method Get -TimeoutSec 5 -ErrorAction Stop
        $ready = $true
        break
    } catch {
        if ($jinxProc.HasExited) {
            Write-Warning "Jinx server process exited (exit code: $($jinxProc.ExitCode))."
            if (Test-Path $JinxLog) {
                Write-Host "--- Server error log ($JinxLog) ---"
                Get-Content $JinxLog -Tail 40
                Write-Host "--- Fix: In a terminal run: cd $AgentDir; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt ---"
            } else {
                Write-Host "Run this to see the error: cd $AgentDir; .\venv\Scripts\Activate.ps1; python -m uvicorn main:app --host 127.0.0.1 --port 8000"
            }
            break
        }
    }
}

if (-not $ready) {
    if ($jinxProc -and -not $jinxProc.HasExited) {
        Write-Warning "Jinx server may still be loading the model. Cursor will start; try the Jinx model in a minute."
    } else {
        Write-Warning "Jinx server did not start. Run: cd $AgentDir; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt"
    }
} else {
    Write-Host "Jinx server is up."
}

Write-Host "Starting Cursor. This window will stay open until you close Cursor."
# Minimize this console so only Cursor is visible (ignore errors if not run from a console)
try {
    Add-Type -Name Win -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);' -Namespace Native -ErrorAction SilentlyContinue
    $hwnd = (Get-Process -Id $PID).MainWindowHandle
    if ($hwnd -ne [IntPtr]::Zero) { [Native.Win]::ShowWindow($hwnd, 6) }  # 6 = SW_MINIMIZE
} catch { }

Start-Process $CursorExe

# Wait until Cursor is closed
while (Get-Process -Name "Cursor" -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 2
}

# Cursor closed — stop Jinx
if ($jinxProc -and -not $jinxProc.HasExited) {
    $jinxProc.Kill()
    Write-Host "Jinx server stopped."
}
