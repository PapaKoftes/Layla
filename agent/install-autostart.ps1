# One-time: create scheduled task to start Jinx at Windows logon
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-jinx-server.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName "Jinx Agent Server" -Action $action -Trigger $trigger -Force
Write-Host "Done. Jinx will start at logon. To disable: Unregister-ScheduledTask -TaskName 'Jinx Agent Server'"
