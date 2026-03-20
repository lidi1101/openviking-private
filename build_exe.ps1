[CmdletBinding()]
param(
    [switch]$clean,
    [switch]$rebuild,
    [switch]$AutoInstall,
    [ValidateSet("onefile", "onedir")]
    [string]$Mode = "onefile"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packagingConfigPath = Join-Path $projectRoot "packaging_config.ps1"
if (-not (Test-Path $packagingConfigPath)) {
    throw "Packaging config not found: $packagingConfigPath"
}
. $packagingConfigPath

$specPath = Join-Path $projectRoot $SpecFileName
$distDir = Join-Path $projectRoot "dist"
$buildDir = Join-Path $projectRoot "build"
$exePath = if ($Mode -eq "onedir") {
    Join-Path $distDir "$PackageName\$PackageName.exe"
} else {
    Join-Path $distDir "$PackageName.exe"
}
$legacyOneDirPath = Join-Path $distDir $PackageName
$requiredArtifacts = @(
    (Join-Path $projectRoot "openviking\lib\libagfsbinding.dll")
)
$bundledMingwRoot = Join-Path $projectRoot "third_party\mingw64"
$bundledMingwBin = Join-Path $bundledMingwRoot "bin"

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

function Build-RuntimeArtifactsLocally {
    Write-Host "Trying local runtime artifact build via setup.py build_ext --inplace..."
    $env:OV_DISABLE_OV_CLI = "1"
    $env:OV_DISABLE_AGFS_SERVER = "1"
    Invoke-Python -PythonCmd $pythonCmd -Arguments @("setup.py", "build_ext", "--inplace")
}

function Install-EditableProject {
    Write-Host "Falling back to editable install for runtime artifacts..."
    $env:OV_DISABLE_OV_CLI = "1"
    $env:OV_DISABLE_AGFS_SERVER = "1"
    Invoke-Python -PythonCmd $pythonCmd -Arguments @("-m", "pip", "install", "-e", ".")
}

function Test-CommandAvailable {
    param(
        [string]$CommandName
    )

    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function Get-ResolvedCommandSource {
    param(
        [string]$CommandName
    )

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if (-not $command) {
        return $null
    }

    return $command.Source
}

function Initialize-BundledToolchain {
    if (-not (Test-Path $bundledMingwBin)) {
        return
    }

    $hasBundledGcc = (Test-Path (Join-Path $bundledMingwBin "gcc.exe"))
    $hasBundledGxx = (Test-Path (Join-Path $bundledMingwBin "g++.exe"))
    if (-not ($hasBundledGcc -and $hasBundledGxx)) {
        return
    }

    $pathEntries = @($env:PATH -split ";" | Where-Object { $_ })
    if ($pathEntries -contains $bundledMingwBin) {
        return
    }

    $env:PATH = "$bundledMingwBin;$env:PATH"
    Write-Host "Using bundled MinGW toolchain: $bundledMingwBin"
}

function Show-ResolvedToolchain {
    $toolchainLines = @()
    foreach ($tool in @("cmake", "gcc", "g++", "mingw32-make")) {
        $source = Get-ResolvedCommandSource $tool
        if ($source) {
            $toolchainLines += "  $tool -> $source"
        }
    }

    if ($toolchainLines.Count -gt 0) {
        Write-Host "Resolved toolchain:"
        $toolchainLines | ForEach-Object { Write-Host $_ }
    }
}

function Initialize-SetuptoolsScmFallback {
    $normalizedDistName = "OPENVIKING"
    $pretendVersionEnvName = "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_${normalizedDistName}"
    $genericPretendVersionEnvName = "SETUPTOOLS_SCM_PRETEND_VERSION"

    $existingPretendVersion = Get-Item -Path "Env:$pretendVersionEnvName" -ErrorAction SilentlyContinue
    $existingGenericPretendVersion = Get-Item -Path "Env:$genericPretendVersionEnvName" -ErrorAction SilentlyContinue
    if ($existingPretendVersion -or $existingGenericPretendVersion) {
        return
    }

    if (Test-CommandAvailable "git") {
        return
    }

    $versionFile = Join-Path $projectRoot "openviking\_version.py"
    if (-not (Test-Path $versionFile)) {
        return
    }

    $versionLine = Select-String -Path $versionFile -Pattern "^__version__\s*=\s*version\s*=\s*'([^']+)'" |
        Select-Object -First 1
    if (-not $versionLine) {
        return
    }

    $pretendVersion = $versionLine.Matches[0].Groups[1].Value
    if (-not $pretendVersion) {
        return
    }

    Set-Item -Path "Env:$pretendVersionEnvName" -Value $pretendVersion
    Set-Item -Path "Env:$genericPretendVersionEnvName" -Value $pretendVersion
    Write-Host "git not found. Using setuptools-scm fallback version: $pretendVersion"
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
        foreach ($pythonModule in @(
            @{ Name = "pybind11"; Hint = "pybind11 (install with: pip install pybind11)" },
            @{ Name = "setuptools"; Hint = "setuptools (install with: pip install -U setuptools)" },
            @{ Name = "wheel"; Hint = "wheel (install with: pip install wheel)" }
        )) {
            try {
                Invoke-Python -PythonCmd $pythonCmd -Arguments @("-c", "import $($pythonModule.Name)")
            } catch {
                $missing += $pythonModule.Hint
            }
        }

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
Close $PackageName.exe and any process using files under this path, then retry.
"@
    }
}

Write-Host "Project root: $projectRoot"
Write-Host "Package name: $PackageName"

$pythonCmd = Get-PythonCommand
Write-Host "Using Python: $pythonCmd"
Write-Host "Build mode: $Mode"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:OV_PYINSTALLER_MODE = $Mode
$env:OV_PACKAGE_NAME = $PackageName
Initialize-BundledToolchain
Show-ResolvedToolchain
Initialize-SetuptoolsScmFallback

if (-not (Test-Path $specPath)) {
    throw "Spec file not found: $specPath"
}

if ($clean) {
    Remove-PathIfExists -PathToRemove $buildDir
    Remove-PathIfExists -PathToRemove $distDir
} elseif ($Mode -eq "onefile" -and (Test-Path $legacyOneDirPath)) {
    Write-Host "Removing legacy onedir output..."
    Remove-PathIfExists -PathToRemove $legacyOneDirPath
}

if ($rebuild) {
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
    $missingArtifacts = Get-MissingArtifacts

    if ($missingArtifacts.Count -gt 0) {
        Build-RuntimeArtifactsLocally
        $missingArtifacts = Get-MissingArtifacts
    }

    if ($missingArtifacts.Count -gt 0 -and $AutoInstall) {
        Install-EditableProject
        $missingArtifacts = Get-MissingArtifacts
    }
}

if ($missingArtifacts.Count -gt 0) {
    $nextStep = if (-not $AutoInstall) {
        "Automatic pip installation is disabled unless you pass -AutoInstall."
    } else {
        "Local build and editable install were attempted, but the artifacts are still missing."
    }
    throw @"
Missing required runtime artifacts:
$($missingArtifacts -join "`n")

$nextStep
"@
}

Write-Host "Checking packaging prerequisites..."
Assert-PackagingPrerequisites -NeedsArtifactBuild $false
Write-Host "Checking runtime config..."
Assert-OpenVikingConfig

Write-Host "Building $PackageName.exe..."
Invoke-Python -PythonCmd $pythonCmd -Arguments @("-m", "PyInstaller", "--noconfirm", $specPath)

if (-not (Test-Path $exePath)) {
    throw "Build finished but exe was not found: $exePath"
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $exePath"
