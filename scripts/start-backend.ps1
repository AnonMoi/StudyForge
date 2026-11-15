[CmdletBinding()]
param(
    [string]$BindHost = $(if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }),
    [int]$Port = $(if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }),
    [int]$Workers = $(if ($env:API_WORKERS) { [int]$env:API_WORKERS } else { 1 }),
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repositoryRoot "backend"
. (Join-Path $PSScriptRoot "resolve-python.ps1")

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}
if ($Workers -lt 1) {
    throw "Workers must be at least 1."
}

Push-Location $backendRoot
try {
    $env:API_WORKERS = "$Workers"
    $python = Resolve-ProjectPython -RequireBackendDependencies
    $pythonDirectory = Split-Path -Parent $python
    $env:Path = "$pythonDirectory;$env:Path"
    if ($env:PROJECT_PYTHONPATH) {
        $env:PYTHONPATH = $env:PROJECT_PYTHONPATH
    }
    if ($ValidateOnly) {
        & $python -c "from app.config import settings, validate_runtime_config; import json; report = validate_runtime_config(settings); print(json.dumps(report, ensure_ascii=False)); raise SystemExit(0 if report['valid'] else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "Runtime configuration validation failed."
        }
        exit 0
    }

    & $python -m uvicorn app.main:app --host $BindHost --port $Port --workers $Workers
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
