[CmdletBinding()]
param(
    [string]$BindHost = $(if ($env:FRONTEND_HOST) { $env:FRONTEND_HOST } else { "127.0.0.1" }),
    [int]$Port = $(if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }),
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repositoryRoot "frontend"
$nodeCandidates = [System.Collections.Generic.List[string]]::new()
if ($env:NODE_EXECUTABLE) {
    $nodeCandidates.Add($env:NODE_EXECUTABLE)
}
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) {
    $nodeCandidates.Add($nodeCommand.Source)
}
$npmCommand = Get-Command npm -ErrorAction SilentlyContinue
$nodeExecutable = $nodeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1

if (-not $nodeExecutable) {
    throw "No usable Node.js executable was found. Set NODE_EXECUTABLE to a working node.exe."
}

$typescriptCli = Join-Path $frontendRoot "node_modules\typescript\bin\tsc"
$viteCli = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"

function Invoke-FrontendBuild {
    if ($npmCommand) {
        $null = & $npmCommand.Source run build
        return $LASTEXITCODE
    }

    if (-not (Test-Path -LiteralPath $typescriptCli -PathType Leaf) -or -not (Test-Path -LiteralPath $viteCli -PathType Leaf)) {
        throw "npm is unavailable and frontend node_modules are incomplete; run npm install in frontend/."
    }
    $null = & $nodeExecutable $typescriptCli -b
    if ($LASTEXITCODE -ne 0) {
        return $LASTEXITCODE
    }
    $null = & $nodeExecutable $viteCli build
    return $LASTEXITCODE
}

function Invoke-FrontendPreview {
    if ($npmCommand) {
        $null = & $npmCommand.Source run preview -- --host $BindHost --port $Port
        return $LASTEXITCODE
    }

    if (-not (Test-Path -LiteralPath $viteCli -PathType Leaf)) {
        throw "npm is unavailable and Vite is not installed in frontend/node_modules."
    }
    $null = & $nodeExecutable $viteCli preview --host $BindHost --port $Port
    return $LASTEXITCODE
}

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

Push-Location $frontendRoot
try {
    $buildExitCode = Invoke-FrontendBuild
    if ($buildExitCode -ne 0) {
        throw "Frontend production build failed."
    }
    if ($ValidateOnly) {
        exit 0
    }

    $previewExitCode = Invoke-FrontendPreview
    exit $previewExitCode
}
finally {
    Pop-Location
}
