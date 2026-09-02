$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot ".runtime\server.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "JanitorJAV is not running (PID file not found)."
    exit 0
}

$ServerPid = Get-Content $PidFile
$Process = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
if ($Process) {
    Stop-Process -Id $ServerPid
    $Process.WaitForExit(10000)
}
Remove-Item $PidFile -Force
Write-Host "JanitorJAV stopped."

