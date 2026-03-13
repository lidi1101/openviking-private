$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultEnvPrefix = Join-Path $HOME ".conda\envs\mem"
$envPrefix = if ($env:OPENVIKING_ENV_PREFIX) { $env:OPENVIKING_ENV_PREFIX } else { $defaultEnvPrefix }
$pythonExe = Join-Path $envPrefix "python.exe"
$proxyScript = Join-Path $PSScriptRoot "honor_embedding_proxy.py"
$defaultSourceFile = Join-Path $HOME "Downloads\emb_requests.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

if (-not (Test-Path $proxyScript)) {
    throw "Proxy script not found: $proxyScript"
}

if (-not $env:HONOR_EMBED_SOURCE_FILE -and (Test-Path $defaultSourceFile)) {
    $env:HONOR_EMBED_SOURCE_FILE = $defaultSourceFile
}

$env:PATH = @(
    (Join-Path $envPrefix "Scripts")
    (Join-Path $envPrefix "Library\bin")
    (Join-Path $envPrefix "Library\mingw-w64\bin")
    $env:PATH
) -join ";"

Set-Location $repoRoot

Write-Host "Using env: $envPrefix"
Write-Host "Proxy script: $proxyScript"
if ($env:HONOR_EMBED_SOURCE_FILE) {
    Write-Host "Embedding source: $env:HONOR_EMBED_SOURCE_FILE"
}

& $pythonExe $proxyScript @args
