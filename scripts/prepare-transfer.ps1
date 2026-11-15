[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [string]$DataRoot,
    [switch]$PreviewData,
    [switch]$IncludeData
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repositoryRoot "transfer-output"
}
if (-not $DataRoot) {
    $DataRoot = Join-Path $repositoryRoot "..\data"
}

if ($PreviewData -and $IncludeData) {
    throw "Use either -PreviewData or -IncludeData, not both."
}

function Get-DataInventory {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return [pscustomobject]@{ exists = $false; root = $Root; files = 0; bytes = 0; paths = @() }
    }
    $candidatePaths = @(
        (Join-Path $Root "learning_workstation.db"),
        (Join-Path $Root "notes"),
        (Join-Path $Root "imports"),
        (Join-Path $Root "backups")
    )
    $items = @($candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object {
        if (Test-Path -LiteralPath $_ -PathType Container) {
            Get-ChildItem -LiteralPath $_ -Recurse -File -Force -ErrorAction SilentlyContinue
        } else {
            Get-Item -LiteralPath $_ -Force
        }
    })
    [pscustomobject]@{
        exists = $true
        root = (Resolve-Path -LiteralPath $Root).Path
        files = $items.Count
        bytes = [int64](($items | Measure-Object -Property Length -Sum).Sum)
        paths = @($items | ForEach-Object { $_.FullName.Substring((Resolve-Path -LiteralPath $Root).Path.Length).TrimStart('\') } | Select-Object -First 200)
    }
}

$dataInventory = Get-DataInventory -Root $DataRoot
if ($PreviewData) {
    $dataInventory | ConvertTo-Json -Depth 4
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$packageName = "LearningWorkstation-transfer-$stamp"
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$packageRoot = Join-Path $outputRoot $packageName
$zipPath = Join-Path $outputRoot "$packageName.zip"

if ((Test-Path -LiteralPath $packageRoot -PathType Container) -or (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
    throw "Output already exists: $packageName"
}

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

$excludedDirectories = @(
    ".git", ".runtime", ".vite", ".skill-bulk", ".pytest_cache",
    "backend\.venv", "backend\.venv312", "backend\.venv311", "backend\.runtime",
    "frontend\node_modules", "frontend\dist", ".agents\inspection-data",
    "transfer-output"
)
$excludedFilePatterns = @(
    ".env", "*.db", "*.sqlite", "*.sqlite3", "*.log", "*.pyc", "*.tsbuildinfo",
    "*.tmp"
)

$included = [System.Collections.Generic.List[string]]::new()
$excluded = [System.Collections.Generic.List[string]]::new()
$rootPrefix = $repositoryRoot.TrimEnd('\') + '\'

$files = @(Get-ChildItem -LiteralPath $repositoryRoot -Recurse -File -Force -ErrorAction SilentlyContinue)
foreach ($file in $files) {
    $relative = $file.FullName.Substring($rootPrefix.Length)
    $normalized = $relative.Replace('/', '\')
    $parts = $normalized.Split('\')
    $isExcluded = $false

    foreach ($directory in $excludedDirectories) {
        if ($normalized.Equals($directory, [System.StringComparison]::OrdinalIgnoreCase) -or
            $normalized.StartsWith($directory.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            $isExcluded = $true
            break
        }
    }
    if (-not $isExcluded -and ($parts | Where-Object { $_ -like '.pytest*' }).Count -gt 0) {
        $isExcluded = $true
    }
    if (-not $isExcluded) {
        foreach ($pattern in $excludedFilePatterns) {
            if ($file.Name -like $pattern) {
                $isExcluded = $true
                break
            }
        }
    }
    if (-not $isExcluded -and $parts.Count -eq 1 -and $file.Extension -in @('.png', '.jpg', '.jpeg', '.webp')) {
        $isExcluded = $true
    }

    if ($isExcluded) {
        $excluded.Add($normalized)
        continue
    }

    $target = Join-Path $packageRoot $normalized
    $targetDirectory = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    $included.Add($normalized)
}

if ($IncludeData -and $dataInventory.exists) {
    $dataTarget = Join-Path $packageRoot "data"
    New-Item -ItemType Directory -Path $dataTarget -Force | Out-Null
    $dataRootResolved = $dataInventory.root
    $dataCandidates = @(
        (Join-Path $dataRootResolved "learning_workstation.db"),
        (Join-Path $dataRootResolved "notes"),
        (Join-Path $dataRootResolved "imports"),
        (Join-Path $dataRootResolved "backups")
    )
    $dataFiles = @($dataCandidates | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object {
        if (Test-Path -LiteralPath $_ -PathType Container) {
            Get-ChildItem -LiteralPath $_ -Recurse -File -Force
        } else {
            Get-Item -LiteralPath $_ -Force
        }
    })
    foreach ($file in $dataFiles) {
        $relative = $file.FullName.Substring($dataRootResolved.TrimEnd('\').Length).TrimStart('\')
        $target = Join-Path $dataTarget $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $included.Add((Join-Path "data" $relative).Replace('/', '\'))
    }
}

$manifest = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    source_root = $repositoryRoot
    package_name = $packageName
    included_data = [bool]$IncludeData
    data_inventory = $dataInventory
    included_file_count = $included.Count
    excluded_file_count = $excluded.Count
    included_files = @($included | Sort-Object)
    excluded_files = @($excluded | Sort-Object)
    security_note = "Secrets and .env are excluded. Review the transfer handoff before configuring the new machine."
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $packageRoot "TRANSFER_MANIFEST.json") -Encoding UTF8

Compress-Archive -Path (Join-Path $packageRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
Write-Output "Package directory: $packageRoot"
Write-Output "ZIP package: $zipPath"
Write-Output "Included files: $($included.Count)"
Write-Output "Excluded files: $($excluded.Count)"
Write-Output "Data included: $([bool]$IncludeData)"
