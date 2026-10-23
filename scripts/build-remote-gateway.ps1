param(
    [string]$DotnetPath = "dotnet",
    [ValidateSet("win-x64")] [string]$RuntimeIdentifier = "win-x64"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "gateway-build-integrity.ps1")
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$projectPath = Join-Path $repositoryRoot "3_PyWebView\gateway\windows\TianceRemoteGateway\TianceRemoteGateway.csproj"
$outputPath = Join-Path $repositoryRoot "runtime\gateway"

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
$stage = Join-Path $temporaryRoot ("tiance-gateway-build-" + [guid]::NewGuid().ToString("N"))
if (-not $stage.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($stage) -notmatch '^tiance-gateway-build-[0-9a-f]{32}$') { throw "Unexpected gateway staging path." }

$inputs = @(Get-GatewayBuildInputs -Root $repositoryRoot)
$sdkVersion = (& $DotnetPath --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Cannot read .NET SDK version." }
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    & $DotnetPath publish $projectPath `
        --configuration Release `
        --runtime $RuntimeIdentifier `
        --self-contained true `
        -p:PublishSingleFile=true `
        -p:DebugType=None `
        -p:DebugSymbols=false `
        --output $stage
    if ($LASTEXITCODE -ne 0) { throw "Gateway publish failed with exit code $LASTEXITCODE." }
    Assert-GatewayBuildInputs -Expected $inputs -Actual @(Get-GatewayBuildInputs -Root $repositoryRoot)
    $executable = Join-Path $stage "TianceRemoteGateway.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw "Gateway executable was not produced." }
    $receipt = [ordered]@{
        schemaVersion = 1
        runtimeIdentifier = $RuntimeIdentifier
        sdkVersion = $sdkVersion
        sources = @($inputs)
        artifact = [ordered]@{
            path = "runtime/gateway/TianceRemoteGateway.exe"
            sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
            size = (Get-Item -LiteralPath $executable).Length
        }
    }
    New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
    # Preserve the previous runtime until compilation succeeds.
    $destination = Join-Path $outputPath "TianceRemoteGateway.exe"
    try {
        Copy-Item -LiteralPath $executable -Destination $destination -Force
    } catch [IO.IOException] {
        # Windows can keep an executable mapped while allowing its name to move.
        # Keep that process alive; install the new file for the next launch.
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw }
        $backupDirectory = Join-Path $repositoryRoot ".codex_tmp/gateway-running"
        New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
        $backup = Join-Path $backupDirectory ("TianceRemoteGateway-" + [guid]::NewGuid().ToString("N") + ".exe")
        $resolvedRoot = [IO.Path]::GetFullPath($repositoryRoot).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (-not [IO.Path]::GetFullPath($destination).StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not [IO.Path]::GetFullPath($backup).StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Gateway replacement path is outside the repository."
        }
        Move-Item -LiteralPath $destination -Destination $backup
        try {
            Copy-Item -LiteralPath $executable -Destination $destination -Force
        } catch {
            # Restore the original name if installing the new binary fails.
            Copy-Item -LiteralPath $backup -Destination $destination -Force
            throw
        }
        Write-Host "Running gateway preserved at $backup; restart Tiance to load the new executable."
    }
    [IO.File]::WriteAllText((Join-Path $outputPath "build-manifest.json"),
        ($receipt | ConvertTo-Json -Depth 5).Replace("`r`n", "`n") + "`n", [Text.UTF8Encoding]::new($false))
    Assert-GatewayBuild -Root $repositoryRoot
    Write-Host "Gateway published: $outputPath"
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
