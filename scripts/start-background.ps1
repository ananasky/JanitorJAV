$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Runtime = Join-Path $ProjectRoot ".runtime"
$Launcher = Join-Path $ProjectRoot "scripts\run-server.cmd"
$TaskName = "JanitorJAV-LocalServer"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run scripts\setup-windows.ps1 first."
}
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Launcher`""
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddDays(1)
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Days 7) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "JanitorJAV scheduled task started at http://127.0.0.1:8765"
