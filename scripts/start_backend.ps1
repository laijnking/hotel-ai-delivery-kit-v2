$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $root ".venv\\Scripts\\python.exe"
$listenHost = "0.0.0.0"
$llmVars = @("QWEN_API_BASE_URL", "QWEN_API_KEY", "QWEN_MODEL", "QWEN_FAST_MODEL", "QWEN_DEEP_MODEL", "QWEN_TIMEOUT", "QWEN_PARSE_POLICY", "QWEN_PARSE_CONFIDENCE_THRESHOLD", "QWEN_EXPLANATION_POLICY")
$dbVars = @("DB_DIALECT", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")

foreach ($name in $llmVars) {
    $userValue = [Environment]::GetEnvironmentVariable($name, "User")
    if (![string]::IsNullOrWhiteSpace($userValue)) {
        Set-Item -Path "Env:$name" -Value $userValue
    }
}

foreach ($name in $dbVars) {
    $userValue = [Environment]::GetEnvironmentVariable($name, "User")
    if (![string]::IsNullOrWhiteSpace($userValue)) {
        Set-Item -Path "Env:$name" -Value $userValue
    }
}

$services = @(
    @{ Name = "auth-service"; Port = 8105; Workdir = "backend\\apps\\auth-service" },
    @{ Name = "metric-service"; Port = 8102; Workdir = "backend\\apps\\metric-service" },
    @{ Name = "semantic-service"; Port = 8101; Workdir = "backend\\apps\\semantic-service" },
    @{ Name = "sql-guardrail-service"; Port = 8103; Workdir = "backend\\apps\\sql-guardrail-service" },
    @{ Name = "db-executor-service"; Port = 8106; Workdir = "backend\\apps\\db-executor-service" },
    @{ Name = "explanation-service"; Port = 8104; Workdir = "backend\\apps\\explanation-service" },
    @{ Name = "audit-service"; Port = 8107; Workdir = "backend\\apps\\audit-service" },
    @{ Name = "ai-query-service"; Port = 8100; Workdir = "backend\\apps\\ai-query-service" }
)

foreach ($service in $services) {
    $workdir = Join-Path $root $service.Workdir
    Write-Host "[start] Launching $($service.Name) on $listenHost`:$($service.Port)"
    Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $listenHost, "--port", "$($service.Port)") `
        -WorkingDirectory $workdir | Out-Null
}

Write-Host "[start] Backend services launched."
