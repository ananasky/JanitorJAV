@echo off
setlocal
cd /d "%~dp0.."
set "PADDLE_PDX_MODEL_SOURCE=BOS"
if not exist ".runtime" mkdir ".runtime"
".venv\Scripts\python.exe" -m janitorjav.cli --no-browser --host 127.0.0.1 --port 8765 --pid-file ".runtime\server.pid" 1>>".runtime\server.stdout.log" 2>>".runtime\server.stderr.log"
