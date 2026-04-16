$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $root ".venv"
$pythonExe = Join-Path $venvPath "Scripts\\python.exe"
$pipExe = Join-Path $venvPath "Scripts\\python.exe"

if (!(Test-Path -LiteralPath $venvPath)) {
    Write-Host "[setup] Creating virtual environment..."
    python -m venv $venvPath
}

Write-Host "[setup] Upgrading pip tooling..."
& $pythonExe -m pip install --upgrade pip setuptools wheel

Write-Host "[setup] Installing backend dependencies..."
& $pipExe -m pip install -r (Join-Path $root "backend\\requirements.txt")

Write-Host "[setup] Installing frontend dependencies..."
Push-Location (Join-Path $root "frontend")
try {
    & npm.cmd install
} finally {
    Pop-Location
}

Write-Host "[setup] Local environment is ready."
