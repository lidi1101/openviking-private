$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultEnvPrefix = Join-Path $HOME ".conda\envs\mem"
$envPrefix = if ($env:OPENVIKING_ENV_PREFIX) { $env:OPENVIKING_ENV_PREFIX } else { $defaultEnvPrefix }
$pythonExe = Join-Path $envPrefix "python.exe"
$defaultConfig = Join-Path $HOME ".openviking\ov.conf"
$defaultCliConfig = Join-Path $HOME ".openviking\ovcli.conf"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

$env:OPENVIKING_CONFIG_FILE = if ($env:OPENVIKING_CONFIG_FILE) {
    $env:OPENVIKING_CONFIG_FILE
} else {
    $defaultConfig
}

$env:OPENVIKING_CLI_CONFIG_FILE = if ($env:OPENVIKING_CLI_CONFIG_FILE) {
    $env:OPENVIKING_CLI_CONFIG_FILE
} else {
    $defaultCliConfig
}

$env:PATH = @(
    (Join-Path $envPrefix "Scripts")
    (Join-Path $envPrefix "Library\bin")
    (Join-Path $envPrefix "Library\mingw-w64\bin")
    $env:PATH
) -join ";"

Set-Location $repoRoot

Write-Host "Using env: $envPrefix"
Write-Host "Server config: $env:OPENVIKING_CONFIG_FILE"
Write-Host "CLI config: $env:OPENVIKING_CLI_CONFIG_FILE"

& $pythonExe -m openviking_cli.server_bootstrap @args
