[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$RebuildArtifacts,
    [ValidateSet("onefile", "onedir")]
    [string]$Mode = "onefile"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$specPath = Join-Path $projectRoot "OpenVikingServer.spec"
$distDir = Join-Path $projectRoot "dist"
$buildDir = Join-Path $projectRoot "build"
$exePath = if ($Mode -eq "onedir") {
    Join-Path $distDir "OpenVikingServer\OpenVikingServer.exe"
} else {
    Join-Path $distDir "OpenVikingServer.exe"
}
$legacyOneDirPath = Join-Path $distDir "OpenVikingServer"
$requiredArtifacts = @(
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

function Test-CommandAvailable {
    param(
        [string]$CommandName
    )

    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function Assert-PackagingPrerequisites {
    param(
        [bool]$NeedsArtifactBuild
    )

    $missing = @()

    if (-not (Test-CommandAvailable "pip")) {
        $missing += "pip"
    }

    try {
        Invoke-Python -PythonCmd $pythonCmd -Arguments @("-c", "import PyInstaller")
    } catch {
        $missing += "PyInstaller (install with: pip install -U pyinstaller)"
    }

    if ($NeedsArtifactBuild) {
        foreach ($tool in @("go", "cmake", "gcc", "g++")) {
            if (-not (Test-CommandAvailable $tool)) {
                $missing += $tool
            }
        }
    }

    if ($missing.Count -gt 0) {
        $items = ($missing | ForEach-Object { "- $_" }) -join "`n"
        throw @"
Missing packaging prerequisites:
$items

Install the missing tools and retry.
"@
    }
}

function Resolve-OvConfigPath {
    if ($env:OPENVIKING_CONFIG_FILE -and (Test-Path $env:OPENVIKING_CONFIG_FILE)) {
        return (Resolve-Path $env:OPENVIKING_CONFIG_FILE).Path
    }

    $userConfig = Join-Path $env:USERPROFILE ".openviking\ov.conf"
    if (Test-Path $userConfig) {
        return $userConfig
    }

    return $null
}

function Assert-OpenVikingConfig {
    $configPath = Resolve-OvConfigPath
    if (-not $configPath) {
        throw @"
OpenViking runtime config not found.

Expected one of:
- %OPENVIKING_CONFIG_FILE%
- $env:USERPROFILE\.openviking\ov.conf

Provide a valid ov.conf before packaging so the runtime configuration is known.
"@
    }

    Write-Host "Using ov.conf: $configPath"

    try {
        $config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Failed to parse ov.conf as JSON: $configPath"
    }

    $agfsMode = $config.storage.agfs.mode
    if (-not $agfsMode) {
        throw "ov.conf is missing storage.agfs.mode: $configPath"
    }

    if ($agfsMode -ne "binding-client") {
        throw @"
ov.conf is not aligned with the current packaging route.

Expected:
- storage.agfs.mode = `"binding-client`"

Found:
- storage.agfs.mode = `"$agfsMode`"

Update the config or switch your packaging approach.
"@
    }
}

function Remove-PathIfExists {
    param(
        [string]$PathToRemove
    )

    if (-not (Test-Path $PathToRemove)) {
        return
    }

    try {
        Remove-Item -Recurse -Force $PathToRemove
    } catch {
        throw @"
Failed to remove path: $PathToRemove

This usually means an old executable or DLL is still running from that location.
Close OpenVikingServer.exe and any process using files under this path, then retry.
"@
    }
}

Write-Host "Project root: $projectRoot"

$pythonCmd = Get-PythonCommand
Write-Host "Using Python: $pythonCmd"
Write-Host "Build mode: $Mode"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:OV_PYINSTALLER_MODE = $Mode

if (-not (Test-Path $specPath)) {
    throw "Spec file not found: $specPath"
}

if ($Clean) {
    Remove-PathIfExists -PathToRemove $buildDir
    Remove-PathIfExists -PathToRemove $distDir
} elseif ($Mode -eq "onefile" -and (Test-Path $legacyOneDirPath)) {
    Write-Host "Removing legacy onedir output..."
    Remove-PathIfExists -PathToRemove $legacyOneDirPath
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
    Assert-PackagingPrerequisites -NeedsArtifactBuild $true
    Write-Host "Missing runtime artifacts detected. Building them via editable install..."
    $env:OV_DISABLE_OV_CLI = "1"
    $env:OV_DISABLE_AGFS_SERVER = "1"
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

Write-Host "Checking packaging prerequisites..."
Assert-PackagingPrerequisites -NeedsArtifactBuild $false
Write-Host "Checking runtime config..."
Assert-OpenVikingConfig

Write-Host "Building OpenVikingServer.exe..."
Invoke-Python -PythonCmd $pythonCmd -Arguments @("-m", "PyInstaller", "--noconfirm", $specPath)

if (-not (Test-Path $exePath)) {
    throw "Build finished but exe was not found: $exePath"
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $exePath"
