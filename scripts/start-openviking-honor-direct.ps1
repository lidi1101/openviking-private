param(
    [string]$ConfigPath = "",
    [string]$EnvPrefix = "",
    [string]$HonorSourcePath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultEnvPrefix = Join-Path $HOME ".conda\envs\mem"
$resolvedEnvPrefix = if ($EnvPrefix) { $EnvPrefix } else { $defaultEnvPrefix }
$pythonExe = Join-Path $resolvedEnvPrefix "python.exe"
$resolvedConfigPath = if ($ConfigPath) { $ConfigPath } else { Join-Path $HOME ".openviking\ov.conf" }
$resolvedHonorSourcePath = if ($HonorSourcePath) { $HonorSourcePath } else { Join-Path $repoRoot "emb_requests.py" }
$runtimeDir = Join-Path $repoRoot ".runtime"
$runtimeConfigPath = Join-Path $runtimeDir "ov.honor.direct.conf"
$runtimeWorkspacePath = Join-Path $runtimeDir "workspace"

function Set-ConfigValue {
    param(
        [Parameter(Mandatory = $true)][object]$Target,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )

    if ($Target.PSObject.Properties[$Name]) {
        $Target.$Name = $Value
    } else {
        $Target | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}
if (-not (Test-Path $resolvedConfigPath)) {
    throw "OpenViking config not found: $resolvedConfigPath"
}
if (-not (Test-Path $resolvedHonorSourcePath)) {
    throw "Honor source file not found: $resolvedHonorSourcePath"
}

$baseConfig = Get-Content -Raw $resolvedConfigPath | ConvertFrom-Json
$sourceText = Get-Content -Raw $resolvedHonorSourcePath

$urlMatch = [regex]::Match($sourceText, 'url\s*=\s*"([^"]+)"')
$akMatch = [regex]::Match($sourceText, 'access_key\s*=\s*"([^"]+)"')
$skMatch = [regex]::Match($sourceText, 'secret_key\s*=\s*"([^"]+)"')
if (-not $urlMatch.Success -or -not $akMatch.Success -or -not $skMatch.Success) {
    throw "Failed to parse Honor URL / AK / SK from $resolvedHonorSourcePath"
}

if (-not $baseConfig.embedding) {
    $baseConfig | Add-Member -NotePropertyName embedding -NotePropertyValue ([pscustomobject]@{}) -Force
}
if (-not $baseConfig.embedding.dense) {
    $baseConfig.embedding | Add-Member -NotePropertyName dense -NotePropertyValue ([pscustomobject]@{}) -Force
}
if (-not $baseConfig.storage) {
    $baseConfig | Add-Member -NotePropertyName storage -NotePropertyValue ([pscustomobject]@{}) -Force
}

Set-ConfigValue -Target $baseConfig.embedding.dense -Name "provider" -Value "honor"
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "api_base" -Value $urlMatch.Groups[1].Value
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "model" -Value $(if ($baseConfig.embedding.dense.model) { $baseConfig.embedding.dense.model } else { "honor-embedding" })
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "dimension" -Value $(if ($baseConfig.embedding.dense.dimension) { [int]$baseConfig.embedding.dense.dimension } else { 768 })
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "timeout_s" -Value 60.0
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "hmac_access_key" -Value $akMatch.Groups[1].Value
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "hmac_secret_key" -Value $skMatch.Groups[1].Value
Set-ConfigValue -Target $baseConfig.embedding.dense -Name "hmac_signed_headers" -Value @("User-Agent")
Set-ConfigValue -Target $baseConfig.storage -Name "workspace" -Value $runtimeWorkspacePath

foreach ($fieldName in @("api_key", "source_file", "source_function")) {
    if ($baseConfig.embedding.dense.PSObject.Properties[$fieldName]) {
        $baseConfig.embedding.dense.PSObject.Properties.Remove($fieldName)
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeWorkspacePath | Out-Null
[System.IO.File]::WriteAllText(
    $runtimeConfigPath,
    ($baseConfig | ConvertTo-Json -Depth 20),
    [System.Text.UTF8Encoding]::new($false)
)

Remove-Item Env:\HONOR_EMBED_SOURCE_FILE -ErrorAction SilentlyContinue
Remove-Item Env:\HONOR_EMBED_SOURCE_FUNCTION -ErrorAction SilentlyContinue
$env:OPENVIKING_CONFIG_FILE = $runtimeConfigPath
$env:PATH = @(
    (Join-Path $resolvedEnvPrefix "Scripts")
    (Join-Path $resolvedEnvPrefix "Library\bin")
    (Join-Path $resolvedEnvPrefix "Library\mingw-w64\bin")
    $env:PATH
) -join ";"

Set-Location $repoRoot

Write-Host "Using env: $resolvedEnvPrefix"
Write-Host "Base config: $resolvedConfigPath"
Write-Host "Runtime config: $runtimeConfigPath"
Write-Host "Honor source: $resolvedHonorSourcePath"
Write-Host "Source-file mode disabled; OpenViking will call Honor directly via HMAC."

& $pythonExe -m openviking_cli.server_bootstrap
