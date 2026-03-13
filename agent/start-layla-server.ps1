# Start Jinx agent server (for Task Scheduler / autostart)
Set-Location $PSScriptRoot
& "$PSScriptRoot\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
