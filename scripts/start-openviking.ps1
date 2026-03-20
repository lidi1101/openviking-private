$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultEnvPrefix = Join-Path $HOME ".conda\envs\mem"
$envPrefix = if ($env:OPENVIKING_ENV_PREFIX) { $env:OPENVIKING_ENV_PREFIX } else { $defaultEnvPrefix }
$pythonExe = Join-Path $envPrefix "python.exe"
$defaultConfig = Join-Path $HOME ".openviking\ov.conf"
$defaultCliConfig = Join-Path $HOME ".openviking\ovcli.conf"
$defaultSourceFile = Join-Path $HOME "Downloads\emb_requests.py"
$repoSourceFile = Join-Path $repoRoot "emb_requests.py"

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

if (-not $env:HONOR_EMBED_SOURCE_FILE) {
    if (Test-Path $defaultSourceFile) {
        $env:HONOR_EMBED_SOURCE_FILE = $defaultSourceFile
    } elseif (Test-Path $repoSourceFile) {
        $env:HONOR_EMBED_SOURCE_FILE = $repoSourceFile
    }
}

function Use-IntegratedHonorEmbeddingConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    if (-not (Test-Path $ConfigPath)) {
        return $ConfigPath
    }

    try {
        $config = Get-Content -Raw $ConfigPath | ConvertFrom-Json
    } catch {
        Write-Warning "Failed to parse config file: $ConfigPath. Starting with the original config."
        return $ConfigPath
    }

    if (-not $config.embedding -or -not $config.embedding.dense) {
        return $ConfigPath
    }

    $dense = $config.embedding.dense
    $apiBase = if ($dense.api_base) { "$($dense.api_base)".TrimEnd("/") } else { "" }
    $isLegacyLocalProxy = (
        $dense.provider -eq "openai" -and (
            $apiBase -eq "http://127.0.0.1:18080/v1" -or
            $apiBase -eq "http://localhost:18080/v1"
        )
    )

    if (-not $isLegacyLocalProxy) {
        return $ConfigPath
    }

    $newDense = [ordered]@{
        provider = "honor"
        model = if ($dense.model) { $dense.model } else { "honor-embedding" }
    }

    if ($null -ne $dense.dimension) {
        $newDense.dimension = [int]$dense.dimension
    }
    if ($env:HONOR_EMBED_API_URL) {
        $newDense.api_base = $env:HONOR_EMBED_API_URL
    }
    if ($env:HONOR_EMBED_SOURCE_FILE) {
        $newDense.source_file = $env:HONOR_EMBED_SOURCE_FILE
    }
    if ($env:HONOR_EMBED_SOURCE_FUNCTION) {
        $newDense.source_function = $env:HONOR_EMBED_SOURCE_FUNCTION
    }
    if ($env:HONOR_EMBED_ACCESS_KEY) {
        $newDense.hmac_access_key = $env:HONOR_EMBED_ACCESS_KEY
    }
    if ($env:HONOR_EMBED_SECRET_KEY) {
        $newDense.hmac_secret_key = $env:HONOR_EMBED_SECRET_KEY
    }
    $newDense.hmac_signed_headers = @("User-Agent")

    $newEmbedding = [ordered]@{
        dense = [pscustomobject]$newDense
    }
    if ($config.embedding.sparse) {
        $newEmbedding.sparse = $config.embedding.sparse
    }
    if ($config.embedding.hybrid) {
        $newEmbedding.hybrid = $config.embedding.hybrid
    }
    if ($null -ne $config.embedding.max_concurrent) {
        $newEmbedding.max_concurrent = [int]$config.embedding.max_concurrent
    }
    $config.embedding = [pscustomobject]$newEmbedding

    $runtimeDir = Join-Path $RepoRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $convertedConfigPath = Join-Path $runtimeDir "ov.integrated.honor.conf"
    $config | ConvertTo-Json -Depth 20 | Set-Content -Path $convertedConfigPath -Encoding UTF8

    Write-Host "Detected legacy local embedding proxy config; switched to integrated Honor embedder."
    return $convertedConfigPath
}

$env:OPENVIKING_CONFIG_FILE = Use-IntegratedHonorEmbeddingConfig -ConfigPath $env:OPENVIKING_CONFIG_FILE -RepoRoot $repoRoot

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
if ($env:HONOR_EMBED_SOURCE_FILE) {
    Write-Host "Honor embedding source: $env:HONOR_EMBED_SOURCE_FILE"
}

& $pythonExe -m openviking_cli.server_bootstrap @args
