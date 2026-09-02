$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Runtime = Join-Path $ProjectRoot ".runtime"
$PidFile = Join-Path $Runtime "server.pid"
$Stdout = Join-Path $Runtime "server.stdout.log"
$Stderr = Join-Path $Runtime "server.stderr.log"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run scripts\setup-windows.ps1 first."
}
if (Test-Path $PidFile) {
    $ExistingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($ExistingPid -and (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue)) {
        Write-Host "JanitorJAV is already running with PID $ExistingPid"
        exit 0
    }
}

New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$env:PADDLE_PDX_MODEL_SOURCE = "BOS"
$Process = Start-Process -FilePath $Python `
    -ArgumentList "-m", "janitorjav.cli", "--no-browser", "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -WindowStyle Hidden `
    -PassThru
$Process.Id | Set-Content -Path $PidFile -Encoding ascii
Write-Host "JanitorJAV started with PID $($Process.Id) at http://127.0.0.1:8765"

