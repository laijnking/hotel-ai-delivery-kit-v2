$ErrorActionPreference = "Stop"

$scriptRoot = $PSScriptRoot
$root = Split-Path -Parent $scriptRoot
$frontendDir = Join-Path $root "frontend"
$stopScript = Join-Path $scriptRoot "stop_local.ps1"
$startScript = Join-Path $scriptRoot "start_local.ps1"

try {
    & $stopScript
    & $startScript
    Push-Location $frontendDir
    npm run test:e2e
}
finally {
    Pop-Location
    & $stopScript
}
