[CmdletBinding()]
param(
    [switch]$rebuild,
    [ValidateSet("onefile", "onedir")]
    [string]$Mode = "onefile"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packScript = Join-Path $projectRoot "pack\package_release.ps1"

if (-not (Test-Path $packScript)) {
    throw "Pack script not found: $packScript"
}

$invokeArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $packScript,
    "-Mode", $Mode
)
if ($rebuild) {
    $invokeArgs += "-rebuild"
}

& powershell @invokeArgs

if ($LASTEXITCODE -ne 0) {
    throw "pack\package_release.ps1 failed with exit code ${LASTEXITCODE}"
}
