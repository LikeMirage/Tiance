param(
    [string]$DotnetPath = "dotnet",
    [string]$RuntimeIdentifier = "win-x64"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$projectPath = Join-Path $repositoryRoot "3_PyWebView\gateway\windows\TianceRemoteGateway\TianceRemoteGateway.csproj"
$outputPath = Join-Path $repositoryRoot "runtime\gateway"

if (-not (Test-Path -LiteralPath $projectPath -PathType Leaf)) {
    throw "Gateway project was not found: $projectPath"
}

$resolvedRepositoryRoot = [IO.Path]::GetFullPath($repositoryRoot).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$resolvedOutputPath = [IO.Path]::GetFullPath($outputPath)
if (-not $resolvedOutputPath.StartsWith($resolvedRepositoryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Gateway output path is outside the repository: $resolvedOutputPath"
}
if (Test-Path -LiteralPath $resolvedOutputPath) {
    Remove-Item -LiteralPath $resolvedOutputPath -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $resolvedOutputPath | Out-Null
& $DotnetPath publish $projectPath `
    --configuration Release `
    --runtime $RuntimeIdentifier `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    --output $resolvedOutputPath
if ($LASTEXITCODE -ne 0) { throw "Gateway publish failed with exit code $LASTEXITCODE." }

$iisModule = Join-Path $resolvedOutputPath "aspnetcorev2_inprocess.dll"
if (Test-Path -LiteralPath $iisModule) {
    Remove-Item -LiteralPath $iisModule -Force
}

$executable = Join-Path $resolvedOutputPath "TianceRemoteGateway.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Gateway executable was not produced: $executable"
}

Write-Host "Gateway published: $executable"
