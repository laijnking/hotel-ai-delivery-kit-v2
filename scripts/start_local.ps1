$ErrorActionPreference = "Stop"

$scriptRoot = $PSScriptRoot

& (Join-Path $scriptRoot "setup_local.ps1")
& (Join-Path $scriptRoot "start_backend.ps1")
& (Join-Path $scriptRoot "start_frontend.ps1")

Write-Host "[start] Waiting for services to initialize..."
Start-Sleep -Seconds 6

$pythonExe = Join-Path (Split-Path -Parent $scriptRoot) ".venv\\Scripts\\python.exe"
& $pythonExe (Join-Path $scriptRoot "smoke_check.py")
