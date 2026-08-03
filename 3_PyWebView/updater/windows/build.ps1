[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectFile = Join-Path $PSScriptRoot "TianceUpdater.csproj"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$builtUpdater = Join-Path $PSScriptRoot "bin\Release\TianceUpdater.exe"
$targetUpdater = Join-Path $projectRoot "system\TianceUpdater.exe"
$msbuildCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\MSBuild.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\MSBuild.exe")
)
$msbuild = $msbuildCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $msbuild) {
    throw "MSBuild for .NET Framework 4 is unavailable."
}

& $msbuild $projectFile /nologo /target:Rebuild /property:Configuration=Release /property:Platform=x64 /verbosity:minimal
if ($LASTEXITCODE -ne 0) {
    throw "Tiance updater build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $builtUpdater)) {
    throw "Tiance updater build completed without producing $builtUpdater."
}

Copy-Item -LiteralPath $builtUpdater -Destination $targetUpdater -Force
Write-Output "Built updater: $targetUpdater"
