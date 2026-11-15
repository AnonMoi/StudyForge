[CmdletBinding()]
param(
    [string]$ApiBaseUrl = $(if ($env:API_BASE_URL) { $env:API_BASE_URL } else { "http://127.0.0.1:8000" })
)

$ErrorActionPreference = "Stop"
$base = $ApiBaseUrl.TrimEnd("/")
$configuration = Invoke-RestMethod -UseBasicParsing "$base/api/config/validate"
if (-not $configuration.valid) {
    $configuration | ConvertTo-Json -Depth 8
    throw "Runtime configuration is invalid."
}

$ready = Invoke-RestMethod -UseBasicParsing "$base/api/ready"
if ($ready.status -ne "ready") {
    $ready | ConvertTo-Json -Depth 8
    throw "Backend is not ready."
}

Write-Output ("Backend ready: {0}; configuration valid for {1}." -f $base, $configuration.environment)
