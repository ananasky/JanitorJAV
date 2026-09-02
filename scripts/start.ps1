$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run scripts\setup-windows.ps1 first."
}

Set-Location $ProjectRoot
$env:PADDLE_PDX_MODEL_SOURCE = "BOS"
& $Python -m janitorjav.cli @args

