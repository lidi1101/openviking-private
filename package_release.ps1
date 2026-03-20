[CmdletBinding()]
param(
    [switch]$rebuild,
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

$distExe = if ($Mode -eq "onedir") {
    Join-Path $projectRoot "dist\$PackageName\$PackageName.exe"
} else {
    Join-Path $projectRoot "dist\$PackageName.exe"
}
$releaseRoot = Join-Path $projectRoot "release"
$releaseAppDir = Join-Path $releaseRoot $PackageName
$releaseExe = Join-Path $releaseAppDir "$PackageName.exe"
$zipPath = Join-Path $releaseRoot "$PackageName-$Mode.zip"
$buildScript = Join-Path $projectRoot "build_exe.ps1"

function Remove-PathIfExists {
    param(
        [string]$PathToRemove
    )

    if (-not (Test-Path $PathToRemove)) {
        return
    }

    try {
        Remove-Item -Recurse -Force -ErrorAction Stop $PathToRemove
    } catch {
        throw @"
Failed to remove path: $PathToRemove

This usually means an old release executable or one of its extracted files is still in use.
Close $PackageName.exe and any process using files under this path, then retry.
"@
    }
}

function Compress-ArchiveWithRetry {
    param(
        [string]$SourcePath,
        [string]$DestinationPath,
        [int]$MaxAttempts = 3
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Compress-Archive -Path $SourcePath -DestinationPath $DestinationPath -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq $MaxAttempts) {
                throw
            }
            Start-Sleep -Milliseconds 750
        }
    }
}

if ($rebuild -or -not (Test-Path $distExe)) {
    Write-Host "Building executable before packaging release..."
    $buildArgs = @("-ExecutionPolicy", "Bypass", "-File", $buildScript, "-clean", "-Mode", $Mode)
    Write-Host ("Invoking: powershell " + ($buildArgs -join " "))
    & powershell @buildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "build_exe.ps1 failed with exit code ${LASTEXITCODE}"
    }
}

if (-not (Test-Path $distExe)) {
    throw "Executable not found: $distExe"
}

Remove-PathIfExists -PathToRemove $releaseAppDir
Remove-PathIfExists -PathToRemove $zipPath

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

if ($Mode -eq "onedir") {
    Write-Host "Copying release directory..."
    Copy-Item -Recurse -Force -ErrorAction Stop (Split-Path $distExe -Parent) $releaseRoot
} else {
    New-Item -ItemType Directory -Force -Path $releaseAppDir | Out-Null
    Write-Host "Copying release executable..."
    Copy-Item -Force -ErrorAction Stop $distExe $releaseExe
}

Write-Host "Creating zip archive..."
Compress-ArchiveWithRetry -SourcePath $releaseAppDir -DestinationPath $zipPath

Write-Host ""
Write-Host "Release package ready:"
Write-Host "  Directory: $releaseAppDir"
Write-Host "  Zip:       $zipPath"
