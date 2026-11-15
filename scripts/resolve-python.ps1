function Resolve-ProjectPython {
    [CmdletBinding()]
    param(
        [switch]$RequireBackendDependencies
    )

    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $backendRoot = Join-Path $repositoryRoot "backend"

    function Test-PathSafe {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [ValidateSet("Any", "Container", "Leaf")][string]$PathType = "Any"
        )

        try {
            return Test-Path -LiteralPath $Path -PathType $PathType -ErrorAction Stop
        } catch {
            return $false
        }
    }

    $venvCandidates = @(
        @{ Python = (Join-Path $backendRoot ".venv312\Scripts\python.exe"); SitePackages = (Join-Path $backendRoot ".venv312\Lib\site-packages") },
        @{ Python = (Join-Path $backendRoot ".venv\Scripts\python.exe"); SitePackages = (Join-Path $backendRoot ".venv\Lib\site-packages") },
        @{ Python = (Join-Path $repositoryRoot "backend.venv\Scripts\python.exe"); SitePackages = (Join-Path $repositoryRoot "backend.venv\Lib\site-packages") }
    )
    $projectSitePackages = @(
        (Join-Path $backendRoot ".venv312\Lib\site-packages"),
        (Join-Path $backendRoot ".venv\Lib\site-packages"),
        (Join-Path $repositoryRoot "backend.venv\Lib\site-packages")
    ) | Where-Object { Test-PathSafe -Path $_ -PathType Container } | Select-Object -First 1
    $candidates = [System.Collections.Generic.List[object]]::new()
    if ($env:PYTHON_EXECUTABLE) {
        $candidates.Add(@{ Python = $env:PYTHON_EXECUTABLE; SitePackages = $projectSitePackages })
    }
    # The project venv may contain a uv trampoline that cannot execute in
    # managed terminals. Prefer the real base interpreter and reuse the venv
    # packages through PYTHONPATH.
    # Python 3.12 is the supported interpreter in the current workstation.
    $candidates.Add(@{ Python = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"); SitePackages = $projectSitePackages })
    $uvPythonRoot = Join-Path $env:APPDATA "uv\python"
    try {
        if (Test-Path -LiteralPath $uvPythonRoot -PathType Container) {
            Get-ChildItem -LiteralPath $uvPythonRoot -Directory -ErrorAction Stop | Where-Object { $_.Name -match "cpython-3\.12" } | Sort-Object Name -Descending | ForEach-Object {
                $candidates.Add(@{ Python = (Join-Path $_.FullName "python.exe"); SitePackages = $projectSitePackages })
            }
        }
    } catch {
        # A managed terminal may be unable to enumerate uv's private cache;
        # explicit and known interpreter candidates remain usable.
    }
    # Keep the confirmed 3.11 installation as a compatibility fallback.
    $candidates.Add(@{ Python = (Join-Path $env:APPDATA "uv\python\cpython-3.11-windows-x86_64-none\python.exe"); SitePackages = $projectSitePackages })
    foreach ($venvCandidate in $venvCandidates) { $candidates.Add($venvCandidate) }

    $uniqueCandidates = [System.Collections.Generic.List[object]]::new()
    $seenCandidates = @{}
    foreach ($candidateInfo in $candidates) {
        if (-not $candidateInfo.Python) {
            continue
        }
        $candidateKey = [string]$candidateInfo.Python
        if (-not $seenCandidates.ContainsKey($candidateKey)) {
            $seenCandidates[$candidateKey] = $true
            $uniqueCandidates.Add($candidateInfo)
        }
    }
    $originalPythonPath = $env:PYTHONPATH
    try {
        foreach ($candidateInfo in $uniqueCandidates) {
            $candidate = $candidateInfo.Python
            if (-not (Test-PathSafe -Path $candidate -PathType Leaf)) {
                continue
            }

            $sitePackages = $candidateInfo.SitePackages
            $nativeSitePackages = @(
                (Join-Path (Split-Path -Parent $candidate) "Lib\site-packages"),
                (Join-Path (Split-Path -Parent (Split-Path -Parent $candidate)) "Lib\site-packages")
            ) | Where-Object { Test-PathSafe -Path $_ -PathType Container } | Select-Object -First 1
            $pythonPathParts = @($nativeSitePackages, $originalPythonPath, $sitePackages) | Where-Object { $_ -and (Test-PathSafe -Path $_ -PathType Container) }
            $env:PYTHONPATH = ($pythonPathParts -join ";")

            try {
                & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" | Out-Null
                $probeVersionExitCode = $LASTEXITCODE
            } catch {
                continue
            }
            if ($probeVersionExitCode -ne 0) {
                continue
            }
            if ($RequireBackendDependencies) {
                try {
                    & $candidate -c "import fastapi, sqlalchemy, uvicorn" | Out-Null
                    $probeDependenciesExitCode = $LASTEXITCODE
                } catch {
                    continue
                }
                if ($probeDependenciesExitCode -ne 0) {
                    continue
                }
            }
            $env:PROJECT_SITE_PACKAGES = $sitePackages
            $env:PROJECT_PYTHONPATH = $env:PYTHONPATH
            return $candidate
        }
    } finally {
        $env:PYTHONPATH = $originalPythonPath
    }

    $requirement = if ($RequireBackendDependencies) { " with FastAPI dependencies" } else { "" }
    throw "No usable Python interpreter$requirement was found. Set PYTHON_EXECUTABLE to a working Python 3.11+ executable. Checked: $(($uniqueCandidates | ForEach-Object { $_.Python }) -join ', ')"
}
