[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$RebuildArtifacts
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$specPath = Join-Path $projectRoot "OpenVikingServer.spec"
$distDir = Join-Path $projectRoot "dist"
$buildDir = Join-Path $projectRoot "build"
$exePath = Join-Path $distDir "OpenVikingServer\OpenVikingServer.exe"
$requiredArtifacts = @(
    (Join-Path $projectRoot "openviking\bin\agfs-server.exe"),
    (Join-Path $projectRoot "openviking\lib\libagfsbinding.dll")
)

function Get-PythonCommand {
    $candidates = @()

    $localPythonRoot = Join-Path $env:LOCALAPPDATA "Python"
    if (Test-Path $localPythonRoot) {
        $candidates += Get-ChildItem -Path $localPythonRoot -Directory -Filter "pythoncore-*" |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "python.exe" }
    }

    $candidates += @(
        "python",
        "py -3",
        "py"
    )

    foreach ($candidate in $candidates) {
        try {
            if ($candidate -like "* *") {
                & $env:ComSpec /c $candidate "-c" "import sys; print(sys.executable)" *> $null
            } else {
                & $candidate "-c" "import sys; print(sys.executable)" *> $null
            }
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
        }
    }

    throw "Could not find a working Python interpreter. Install Python or adjust PATH."
}

function Invoke-Python {
    param(
        [string]$PythonCmd,
        [string[]]$Arguments
    )

    if ($PythonCmd -like "* *") {
        & $env:ComSpec /c $PythonCmd @Arguments
    } else {
        & $PythonCmd @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $PythonCmd $($Arguments -join ' ')"
    }
}

function Get-MissingArtifacts {
    return $requiredArtifacts | Where-Object { -not (Test-Path $_) }
}

Write-Host "Project root: $projectRoot"

$pythonCmd = Get-PythonCommand
Write-Host "Using Python: $pythonCmd"

if (-not (Test-Path $specPath)) {
    throw "Spec file not found: $specPath"
}

if ($Clean) {
    if (Test-Path $buildDir) {
        Remove-Item -Recurse -Force $buildDir
    }
    if (Test-Path $distDir) {
        Remove-Item -Recurse -Force $distDir
    }
}

if ($RebuildArtifacts) {
    Write-Host "Forcing rebuild of runtime artifacts..."
    foreach ($artifact in $requiredArtifacts) {
        if (Test-Path $artifact) {
            Remove-Item -Force $artifact
        }
    }
}

Write-Host "Checking build artifacts..."
$missingArtifacts = Get-MissingArtifacts
if ($missingArtifacts.Count -gt 0) {
    Write-Host "Missing runtime artifacts detected. Building them via editable install..."
    $env:OV_DISABLE_OV_CLI = "1"
    Invoke-Python -PythonCmd $pythonCmd -Arguments @("-m", "pip", "install", "-e", ".")
    $missingArtifacts = Get-MissingArtifacts
}

if ($missingArtifacts.Count -gt 0) {
    throw @"
Missing required runtime artifacts:
$($missingArtifacts -join "`n")

Automatic build was attempted with OV_DISABLE_OV_CLI=1, but the artifacts are still missing.
"@
}

Write-Host "Checking PyInstaller..."
Invoke-Python -PythonCmd $pythonCmd -Arguments @("-c", "import PyInstaller")

Write-Host "Building OpenVikingServer.exe..."
Invoke-Python -PythonCmd $pythonCmd -Arguments @("-m", "PyInstaller", "--noconfirm", $specPath)

if (-not (Test-Path $exePath)) {
    throw "Build finished but exe was not found: $exePath"
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $exePath"
