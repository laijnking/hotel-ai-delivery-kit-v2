$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $root "frontend"
$envPath = Join-Path $frontendDir ".env"
$exampleEnvPath = Join-Path $frontendDir ".env.example"
$logDir = Join-Path $root "runtime\\logs"
$stdoutLog = Join-Path $logDir "frontend.stdout.log"
$stderrLog = Join-Path $logDir "frontend.stderr.log"

if (!(Test-Path -LiteralPath $envPath) -and (Test-Path -LiteralPath $exampleEnvPath)) {
    Copy-Item -LiteralPath $exampleEnvPath -Destination $envPath
}

if (!(Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

Write-Host "[start] Launching frontend on http://0.0.0.0:3000"
Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/c", "npm.cmd run dev -- --host 0.0.0.0 --port 3000") `
    -WorkingDirectory $frontendDir `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog | Out-Null
