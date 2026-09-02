$ErrorActionPreference = "Stop"
$TaskName = "JanitorJAV-LocalServer"

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Host "JanitorJAV is not running (scheduled task not found)."
    exit 0
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "JanitorJAV stopped."
