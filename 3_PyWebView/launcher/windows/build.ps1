[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectFile = Join-Path $PSScriptRoot "TianceLauncher.csproj"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$builtLauncher = Join-Path $PSScriptRoot "bin\Release\Tiance.exe"
$targetLauncher = Join-Path $projectRoot "Tiance.exe"
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
    throw "Tiance launcher build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $builtLauncher)) {
    throw "Tiance launcher build completed without producing $builtLauncher."
}

Copy-Item -LiteralPath $builtLauncher -Destination $targetLauncher -Force
Write-Output "Built launcher: $targetLauncher"
