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
$targetBinaryName = "$PackageName.exe"
$releaseRoot = Join-Path $projectRoot "release"
$releaseAppDir = Join-Path $releaseRoot $PackageName
$releaseExe = Join-Path $releaseAppDir "$PackageName.exe"
$zipPath = Join-Path $releaseRoot "$PackageName-$Mode.zip"
$buildScript = Join-Path $projectRoot "build_exe.ps1"
$stepResults = New-Object System.Collections.Generic.List[object]
$currentStep = $null

function Start-PackagingStep {
    param(
        [string]$Name
    )

    $script:currentStep = [pscustomobject]@{
        Name = $Name
        Status = "running"
        StartedAt = Get-Date
        Detail = $null
    }
    $script:stepResults.Add($script:currentStep) | Out-Null
    Write-Host ""
    Write-Host ("[STEP START] {0}" -f $Name) -ForegroundColor Cyan
}

function Complete-PackagingStep {
    param(
        [string]$Detail
    )

    if (-not $script:currentStep) {
        return
    }

    $script:currentStep.Status = "ok"
    $script:currentStep.Detail = $Detail
    $duration = ((Get-Date) - $script:currentStep.StartedAt).TotalSeconds
    if ($Detail) {
        Write-Host ("[STEP DONE]  {0} ({1:N1}s) - {2}" -f $script:currentStep.Name, $duration, $Detail) -ForegroundColor Green
    } else {
        Write-Host ("[STEP DONE]  {0} ({1:N1}s)" -f $script:currentStep.Name, $duration) -ForegroundColor Green
    }
    $script:currentStep = $null
}

function Fail-PackagingStep {
    param(
        [string]$Detail
    )

    if (-not $script:currentStep) {
        return
    }

    $script:currentStep.Status = "failed"
    $script:currentStep.Detail = $Detail
    $duration = ((Get-Date) - $script:currentStep.StartedAt).TotalSeconds
    if ($Detail) {
        Write-Host ("[STEP FAIL]  {0} ({1:N1}s) - {2}" -f $script:currentStep.Name, $duration, $Detail) -ForegroundColor Magenta
    } else {
        Write-Host ("[STEP FAIL]  {0} ({1:N1}s)" -f $script:currentStep.Name, $duration) -ForegroundColor Magenta
    }
    $script:currentStep = $null
}

function Write-PackagingSummary {
    param(
        [bool]$Succeeded
    )

    Write-Host ""
    Write-Host "Packaging step summary:" -ForegroundColor DarkCyan
    $stepIndex = 1
    foreach ($step in $script:stepResults) {
        $duration = ((Get-Date) - $step.StartedAt).TotalSeconds
        $label = switch ($step.Status) {
            "ok" { "OK" }
            "failed" { "FAILED" }
            default { "RUNNING" }
        }
        $color = switch ($step.Status) {
            "ok" { "Green" }
            "failed" { "Magenta" }
            default { "Cyan" }
        }
        $line = "  {0}. [{1}] {2}" -f $stepIndex, $label, $step.Name
        if ($step.Detail) {
            $line += " - $($step.Detail)"
        }
        $line += " ({0:N1}s)" -f $duration
        Write-Host $line -ForegroundColor $color
        $stepIndex += 1
    }

    Write-Host ""
    if ($Succeeded) {
        Write-Host "Release packaging finished successfully." -ForegroundColor Green
    } else {
        Write-Host "Release packaging finished with errors." -ForegroundColor Magenta
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

$packageSucceeded = $false

try {
    if ($rebuild -or -not (Test-Path $distExe)) {
        Start-PackagingStep "Build $targetBinaryName"
        Write-Host "Building executable before packaging release..."
        $buildArgs = @("-ExecutionPolicy", "Bypass", "-File", $buildScript, "-clean", "-Mode", $Mode)
        Write-Host ("Invoking: powershell " + ($buildArgs -join " "))
        & powershell @buildArgs
        if ($LASTEXITCODE -ne 0) {
            throw "build_exe.ps1 failed with exit code ${LASTEXITCODE}"
        }
        Complete-PackagingStep "$targetBinaryName rebuilt"
    }

    Start-PackagingStep "Validate $targetBinaryName output"
    if (-not (Test-Path $distExe)) {
        throw "Executable not found: $distExe"
    }
    Complete-PackagingStep "Using $targetBinaryName from $distExe"

    Start-PackagingStep "Prepare release directory for $targetBinaryName"
    Remove-PathIfExists -PathToRemove $releaseAppDir
    Remove-PathIfExists -PathToRemove $zipPath
    New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
    Complete-PackagingStep "Release directory prepared"

    Start-PackagingStep "Copy release payload for $targetBinaryName"
    if ($Mode -eq "onedir") {
        Write-Host "Copying release directory..."
        Copy-Item -Recurse -Force -ErrorAction Stop (Split-Path $distExe -Parent) $releaseRoot
    } else {
        New-Item -ItemType Directory -Force -Path $releaseAppDir | Out-Null
        Write-Host "Copying release executable..."
        Copy-Item -Force -ErrorAction Stop $distExe $releaseExe
    }
    Complete-PackagingStep "Release payload copied for $targetBinaryName"

    Start-PackagingStep "Create release archive for $targetBinaryName"
    Write-Host "Creating zip archive..."
    Compress-ArchiveWithRetry -SourcePath $releaseAppDir -DestinationPath $zipPath
    Complete-PackagingStep "Created $zipPath"

    $packageSucceeded = $true
    Write-Host ""
    Write-Host "Release package ready:"
    Write-Host "  Directory: $releaseAppDir"
    Write-Host "  Zip:       $zipPath"
} catch {
    Fail-PackagingStep $_.Exception.Message
    throw
} finally {
    Write-PackagingSummary -Succeeded $packageSucceeded
}
