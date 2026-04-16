$ErrorActionPreference = "SilentlyContinue"

$ports = 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107, 3000

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "[stop] Local frontend/backend processes stopped for known ports."
