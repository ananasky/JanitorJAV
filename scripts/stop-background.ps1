$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TaskName = "JanitorJAV-LocalServer"
$PidFile = Join-Path $ProjectRoot ".runtime\server.pid"

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -and -not (Test-Path $PidFile)) {
    Write-Host "JanitorJAV is not running (scheduled task not found)."
    exit 0
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
if (Test-Path $PidFile) {
    $ServerPid = [int](Get-Content $PidFile)
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ServerPid" -ErrorAction SilentlyContinue
    if ($Process -and $Process.CommandLine -like "*janitorjav.cli*") {
        & taskkill.exe /PID $ServerPid /T /F | Out-Null
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
Write-Host "JanitorJAV stopped."
