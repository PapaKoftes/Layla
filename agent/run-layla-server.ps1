# Run Jinx server in this window (so you see any errors). Use for debugging.
# Normal use: start Cursor via Start-Cursor-With-Jinx.ps1 instead.
Set-Location $PSScriptRoot
& "$PSScriptRoot\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
