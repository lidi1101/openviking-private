[CmdletBinding()]
param(
    [switch]$clean,
    [switch]$rebuild,
    [switch]$AutoInstall,
    [ValidateSet("onefile", "onedir")]
    [string]$Mode = "onefile"
)

$ErrorActionPreference = "Stop"

$packRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $packRoot
$packagingConfigPath = Join-Path $packRoot "packaging_config.ps1"
if (-not (Test-Path $packagingConfigPath)) {
    throw "Packaging config not found: $packagingConfigPath"
}
. $packagingConfigPath

$specPath = Join-Path $packRoot $SpecFileName
$distDir = Join-Path $packRoot "dist"
$buildDir = Join-Path $packRoot "build"
$targetBinaryName = "$PackageName.exe"
$exePath = if ($Mode -eq "onedir") {
    Join-Path $distDir "$PackageName\$targetBinaryName"
} else {
    Join-Path $distDir $targetBinaryName
}
$legacyOneDirPath = Join-Path $distDir $PackageName
$requiredArtifacts = @(
    (Join-Path $projectRoot "openviking\lib\libagfsbinding.dll")
)
$bundledMingwRoot = Join-Path $projectRoot "third_party\mingw64"
$bundledMingwBin = Join-Path $bundledMingwRoot "bin"
$bundledMingwArchives = @(
    (Join-Path $projectRoot "third_party\mingw64.7z.001"),
    (Join-Path $projectRoot "third_party\mingw64.7z"),
    (Join-Path $projectRoot "third_party\mingw64.zip")
)
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
        EndedAt = $null
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
    $script:currentStep.EndedAt = Get-Date
    $script:currentStep.Detail = $Detail
    $duration = ($script:currentStep.EndedAt - $script:currentStep.StartedAt).TotalSeconds
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
    $script:currentStep.EndedAt = Get-Date
    $script:currentStep.Detail = $Detail
    $duration = ($script:currentStep.EndedAt - $script:currentStep.StartedAt).TotalSeconds
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
        $endedAt = if ($step.EndedAt) { $step.EndedAt } else { Get-Date }
        $duration = ($endedAt - $step.StartedAt).TotalSeconds
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
        Write-Host "Packaging finished successfully." -ForegroundColor Green
    } else {
        Write-Host "Packaging finished with errors." -ForegroundColor Magenta
    }
}

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

function Get-PythonVersionString {
    param(
        [string]$PythonCmd
    )

    if ($PythonCmd -like "* *") {
        return (& $env:ComSpec /c $PythonCmd "-c" "import platform; print(platform.python_version())")
    }

    return (& $PythonCmd "-c" "import platform; print(platform.python_version())")
}

function Get-MissingArtifacts {
    return $requiredArtifacts | Where-Object { -not (Test-Path $_) }
}

function Get-ArtifactNames {
    param(
        [string[]]$ArtifactPaths
    )

    return $ArtifactPaths | ForEach-Object { Split-Path $_ -Leaf }
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

function Assert-RuntimePythonDependencies {
    $missing = @()

    foreach ($pythonModule in @(
        @{ Name = "fastapi"; Hint = "fastapi (install with: pip install fastapi)" },
        @{ Name = "starlette"; Hint = "starlette (install with: pip install starlette)" },
        @{ Name = "uvicorn"; Hint = "uvicorn (install with: pip install uvicorn)" },
        @{ Name = "multipart"; Hint = "python-multipart (install with: pip install python-multipart)" },
        @{ Name = "httpx"; Hint = "httpx (install with: pip install httpx)" },
        @{ Name = "pydantic"; Hint = "pydantic (install with: pip install pydantic)" }
    )) {
        try {
            Invoke-Python -PythonCmd $pythonCmd -Arguments @("-c", "import $($pythonModule.Name)")
        } catch {
            $missing += $pythonModule.Hint
        }
    }

    if ($missing.Count -gt 0) {
        $items = ($missing | ForEach-Object { "- $_" }) -join "`n"
        throw @"
Missing required runtime Python dependencies for packaging:
$items

The executable can be built with missing imports, but it will fail at startup.
Install the missing packages into the same Python environment used for packaging,
or run:
  pip install -e .
"@
    }
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

function Get-ArchiveExtractor {
    $candidates = @(
        "7z",
        "7za",
        "7zr",
        (Join-Path ${env:ProgramFiles} "7-Zip\7z.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "7-Zip\7z.exe")
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if ($candidate -like "*.exe") {
            if (Test-Path $candidate) {
                return $candidate
            }
            continue
        }

        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    return $null
}

function Expand-ArchiveWithShell {
    param(
        [string]$ArchivePath,
        [string]$DestinationPath
    )

    $shell = New-Object -ComObject Shell.Application
    $archiveNamespace = $shell.NameSpace($ArchivePath)
    $destinationNamespace = $shell.NameSpace($DestinationPath)

    if (-not $archiveNamespace -or -not $destinationNamespace) {
        return $false
    }

    $destinationNamespace.CopyHere($archiveNamespace.Items(), 0x10)
    return $true
}

function Get-BundledToolchainArchivePath {
    foreach ($archivePath in $bundledMingwArchives) {
        if (Test-Path $archivePath) {
            return $archivePath
        }
    }

    return $null
}
function Join-SplitArchiveParts {
    param(
        [string]$FirstPartPath
    )

    $firstPartItem = Get-Item $FirstPartPath
    $partPattern = "{0}.???" -f $firstPartItem.BaseName
    $partItems = @(Get-ChildItem -Path $firstPartItem.DirectoryName -File -Filter $partPattern | Sort-Object Name)
    if ($partItems.Count -eq 0 -or $partItems[0].FullName -ne $firstPartItem.FullName) {
        throw "Split archive parts are incomplete or out of order: $FirstPartPath"
    }

    $mergedArchiveName = "{0}-{1}.7z" -f [System.IO.Path]::GetFileNameWithoutExtension($firstPartItem.BaseName), [guid]::NewGuid().ToString("N")
    $mergedArchivePath = Join-Path ([System.IO.Path]::GetTempPath()) $mergedArchiveName
    $outputStream = [System.IO.File]::Open($mergedArchivePath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)

    try {
        foreach ($partItem in $partItems) {
            $inputStream = [System.IO.File]::OpenRead($partItem.FullName)
            try {
                $inputStream.CopyTo($outputStream)
            } finally {
                $inputStream.Dispose()
            }
        }
    } finally {
        $outputStream.Dispose()
    }

    return $mergedArchivePath
}


function Expand-BundledToolchainArchive {
    param(
        [string]$ArchivePath
    )

    $destinationRoot = Join-Path $projectRoot "third_party"
    $isMultipart7z = $ArchivePath.ToLowerInvariant().EndsWith(".7z.001")
    $extractor = Get-ArchiveExtractor
    if ($extractor) {
        Write-Host "Extracting bundled MinGW toolchain with $extractor ..."
        & $extractor "x" $ArchivePath "-o$destinationRoot" "-y"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract bundled MinGW toolchain from $ArchivePath"
        }
        return
    }

    if ($isMultipart7z) {
        Write-Warning "Detected split 7-Zip archive: $ArchivePath"
        Write-Warning "Split .7z.001 archives are most reliable with 7-Zip. Install 7-Zip if Shell extraction fails."

        if (Test-CommandAvailable "tar") {
            $mergedArchivePath = $null
            try {
                $mergedArchivePath = Join-SplitArchiveParts -FirstPartPath $ArchivePath
                Write-Host "Extracting bundled MinGW toolchain with tar.exe from merged split archive ..."
                & tar "-xf" $mergedArchivePath "-C" $destinationRoot
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to extract bundled MinGW toolchain from merged split archive $ArchivePath with tar.exe"
                }
                return
            } finally {
                if ($mergedArchivePath -and (Test-Path $mergedArchivePath)) {
                    Remove-Item -Path $mergedArchivePath -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }

    if ((-not $isMultipart7z) -and (Test-CommandAvailable "tar") -and $ArchivePath.ToLowerInvariant().EndsWith(".7z")) {
        Write-Host "Extracting bundled MinGW toolchain with tar.exe ..."
        & tar "-xf" $ArchivePath "-C" $destinationRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract bundled MinGW toolchain from $ArchivePath with tar.exe"
        }
        return
    }

    if ($ArchivePath.ToLowerInvariant().EndsWith(".zip")) {
        Write-Host "Extracting bundled MinGW toolchain with Expand-Archive ..."
        Expand-Archive -Path $ArchivePath -DestinationPath $destinationRoot -Force
        return
    }

    Write-Host "Extracting bundled MinGW toolchain with Windows Shell ..."
    $shellExtracted = Expand-ArchiveWithShell -ArchivePath $ArchivePath -DestinationPath $destinationRoot
    if (-not $shellExtracted) {
        $extractorHint = if ($isMultipart7z) {
            "Install 7-Zip, or ensure Windows Shell extraction supports split `.7z.001` archives."
        } elseif ($ArchivePath.ToLowerInvariant().EndsWith(".7z")) {
            "Install 7-Zip, ensure `tar.exe` is available for `.7z`, or enable Windows Shell extraction support."
        } else {
            "Install 7-Zip, use PowerShell Expand-Archive for `.zip`, or enable Windows Shell extraction support."
        }
        throw @"
Bundled MinGW archive found but no supported extractor is available:
- $ArchivePath

$extractorHint
"@
    }

    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Milliseconds 500
        $hasBundledGcc = (Test-Path (Join-Path $bundledMingwBin "gcc.exe"))
        $hasBundledGxx = (Test-Path (Join-Path $bundledMingwBin "g++.exe"))
        if ($hasBundledGcc -and $hasBundledGxx) {
            return
        }
    } while ((Get-Date) -lt $deadline)

    throw "Bundled MinGW extraction via Windows Shell did not complete in time: $ArchivePath"
}

function Ensure-BundledToolchainAvailable {
    $hasBundledGcc = (Test-Path (Join-Path $bundledMingwBin "gcc.exe"))
    $hasBundledGxx = (Test-Path (Join-Path $bundledMingwBin "g++.exe"))
    if ($hasBundledGcc -and $hasBundledGxx) {
        return
    }

    $bundledMingwArchive = Get-BundledToolchainArchivePath
    if (-not $bundledMingwArchive) {
        return
    }

    if (Test-Path $bundledMingwRoot) {
        Remove-Item -Recurse -Force $bundledMingwRoot
    }

    Expand-BundledToolchainArchive -ArchivePath $bundledMingwArchive

    $hasBundledGcc = (Test-Path (Join-Path $bundledMingwBin "gcc.exe"))
    $hasBundledGxx = (Test-Path (Join-Path $bundledMingwBin "g++.exe"))
    if (-not ($hasBundledGcc -and $hasBundledGxx)) {
        throw "Bundled MinGW archive was extracted, but gcc.exe or g++.exe is still missing under $bundledMingwBin"
    }
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
        Ensure-BundledToolchainAvailable
        Initialize-BundledToolchain
        Show-ResolvedToolchain

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

function Sync-OpenVikingConfigFromSample {
    $userConfigDir = Join-Path $env:USERPROFILE ".openviking"
    $userConfigPath = Join-Path $userConfigDir "ov.conf"
    $sampleConfigPath = Join-Path $packRoot "ov-binding-client.example.conf"

    if (-not (Test-Path $sampleConfigPath)) {
        throw "Sample ov.conf not found: $sampleConfigPath"
    }

    if (-not (Test-Path $userConfigDir)) {
        New-Item -ItemType Directory -Force -Path $userConfigDir | Out-Null
    }

    Copy-Item -Force $sampleConfigPath $userConfigPath
    Write-Host "Synced ov.conf from sample: $userConfigPath" -ForegroundColor DarkCyan
    return $userConfigPath
}

function Assert-OpenVikingConfig {
    $configPath = Resolve-OvConfigPath
    if (-not $configPath) {
        $configPath = Sync-OpenVikingConfigFromSample
    } elseif ($configPath -eq (Join-Path $env:USERPROFILE ".openviking\ov.conf")) {
        $configPath = Sync-OpenVikingConfigFromSample
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

$buildSucceeded = $false

try {
    Start-PackagingStep "Initialize environment for $targetBinaryName"
    Write-Host "Project root: $projectRoot"
    Write-Host "Pack root: $packRoot"
    Write-Host "Package name: $PackageName"

    $pythonCmd = Get-PythonCommand
    Write-Host "Using Python: $pythonCmd"
    $pythonVersion = Get-PythonVersionString -PythonCmd $pythonCmd
    Write-Host "Python version: $pythonVersion"
    Write-Host "Build mode: $Mode"
    if ([version]$pythonVersion -ge [version]"3.14.0") {
        Write-Warning "Python 3.14+ is currently high risk for this packaging route because some dependencies still rely on Pydantic V1 compatibility paths. Prefer Python 3.12 for release builds."
    }
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:OV_PYINSTALLER_MODE = $Mode
    $env:OV_PACKAGE_NAME = $PackageName
    Ensure-BundledToolchainAvailable
    Initialize-BundledToolchain
    Show-ResolvedToolchain
    Initialize-SetuptoolsScmFallback

    if (-not (Test-Path $specPath)) {
        throw "Spec file not found: $specPath"
    }
    Complete-PackagingStep "$targetBinaryName build environment resolved"

    Start-PackagingStep "Prepare output directories for $targetBinaryName"
    if ($clean) {
        Remove-PathIfExists -PathToRemove $buildDir
        Remove-PathIfExists -PathToRemove $distDir
    } elseif ($Mode -eq "onefile" -and (Test-Path $legacyOneDirPath)) {
        Write-Host "Removing legacy onedir output..."
        Remove-PathIfExists -PathToRemove $legacyOneDirPath
    }

    if ($rebuild) {
        $artifactNames = (Get-ArtifactNames -ArtifactPaths $requiredArtifacts) -join ", "
        Write-Host "Forcing rebuild of runtime artifacts: $artifactNames"
        foreach ($artifact in $requiredArtifacts) {
            if (Test-Path $artifact) {
                Remove-Item -Force $artifact
            }
        }
    }
    Complete-PackagingStep "Output directories prepared for $targetBinaryName"

    Start-PackagingStep "Prepare runtime artifacts for $targetBinaryName"
    Write-Host "Checking build artifacts..."
    $missingArtifacts = Get-MissingArtifacts
    $initialMissingArtifacts = @($missingArtifacts)
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
    if ($initialMissingArtifacts.Count -gt 0) {
        $rebuiltNames = (Get-ArtifactNames -ArtifactPaths $initialMissingArtifacts) -join ", "
        Complete-PackagingStep "Runtime artifacts are ready for ${targetBinaryName}: $rebuiltNames"
    } else {
        $artifactNames = (Get-ArtifactNames -ArtifactPaths $requiredArtifacts) -join ", "
        Complete-PackagingStep "Runtime artifacts are ready for ${targetBinaryName}: $artifactNames"
    }

    Start-PackagingStep "Validate packaging prerequisites for $targetBinaryName"
    Assert-PackagingPrerequisites -NeedsArtifactBuild $false
    Complete-PackagingStep "Packaging prerequisites validated"

    Start-PackagingStep "Validate runtime Python dependencies for $targetBinaryName"
    Assert-RuntimePythonDependencies
    Complete-PackagingStep "Runtime Python dependencies validated"

    Start-PackagingStep "Validate runtime config for $targetBinaryName"
    Assert-OpenVikingConfig
    Complete-PackagingStep "Runtime config validated"

    Start-PackagingStep "Run PyInstaller for $targetBinaryName"
    Write-Host "Building $targetBinaryName..."
    Invoke-Python -PythonCmd $pythonCmd -Arguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", $distDir,
        "--workpath", $buildDir,
        $specPath
    )

    if (-not (Test-Path $exePath)) {
        throw "Build finished but exe was not found: $exePath"
    }
    Complete-PackagingStep "Generated $targetBinaryName at $exePath"

    $buildSucceeded = $true
    Write-Host ""
    Write-Host "Build complete:"
    Write-Host "  $exePath"
} catch {
    Fail-PackagingStep $_.Exception.Message
    throw
} finally {
    Write-PackagingSummary -Succeeded $buildSucceeded
}

