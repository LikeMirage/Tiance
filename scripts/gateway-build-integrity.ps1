# Bind the exact gateway build inputs to the executable being distributed.
function Get-GatewayBuildInputs {
    param([Parameter(Mandatory = $true)] [string]$Root)
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $project = Join-Path $rootPath "3_PyWebView/gateway/windows/TianceRemoteGateway"
    if (-not (Test-Path -LiteralPath (Join-Path $project "TianceRemoteGateway.csproj") -PathType Leaf)) {
        throw "Gateway build inputs are missing."
    }
    $paths = [Collections.Generic.List[string]]::new()
    foreach ($file in Get-ChildItem -LiteralPath $project -Recurse -File -Force) {
        $relative = $file.FullName.Substring($rootPath.Length + 1).Replace('\', '/')
        if ($relative -match '/(bin|obj)/' -or $file.Name -eq '.gitignore') { continue }
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Gateway build inputs cannot be links: $relative" }
        $paths.Add($relative)
    }
    foreach ($relative in @("scripts/build-remote-gateway.ps1", "scripts/gateway-build-integrity.ps1")) {
        if (-not (Test-Path -LiteralPath (Join-Path $rootPath $relative) -PathType Leaf)) { throw "Missing build input: $relative" }
        $paths.Add($relative)
    }
    # MSBuild and NuGet also discover configuration in project ancestors.
    foreach ($parent in @("", "3_PyWebView/", "3_PyWebView/gateway/", "3_PyWebView/gateway/windows/")) {
        foreach ($name in @("global.json", "NuGet.Config", "nuget.config", "Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props")) {
            $relative = "$parent$name"
            if (Test-Path -LiteralPath (Join-Path $rootPath $relative) -PathType Leaf) {
                if (-not ($paths | Where-Object { $_ -ieq $relative })) { $paths.Add($relative) }
            }
        }
    }
    $paths.Sort([StringComparer]::Ordinal)
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($relative in $paths) {
            $path = Join-Path $rootPath $relative
            if ([IO.Path]::GetExtension($path) -in @('.cs', '.csproj', '.props', '.targets', '.config', '.json', '.ps1')) {
                # Git may check text out as CRLF on Windows and archive it as LF.
                $bytes = [Text.Encoding]::UTF8.GetBytes([IO.File]::ReadAllText($path).Replace("`r`n", "`n"))
            } else { $bytes = [IO.File]::ReadAllBytes($path) }
            [pscustomobject]@{ path = $relative; sha256 = ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
        }
    } finally { $hash.Dispose() }
}

function Assert-GatewayBuildInputs {
    param([object[]]$Expected, [object[]]$Actual)
    $expectedMap = @{}
    foreach ($inputFile in $Expected) {
        if (-not $inputFile.path -or $inputFile.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $expectedMap.ContainsKey($inputFile.path)) {
            throw "Invalid gateway build input receipt."
        }
        $expectedMap[$inputFile.path] = $inputFile.sha256
    }
    if ($expectedMap.Count -ne $Actual.Count) { throw "Gateway build input list changed. Rebuild and commit the gateway EXE and build receipt." }
    foreach ($inputFile in $Actual) {
        if ($expectedMap[$inputFile.path] -cne $inputFile.sha256) {
            throw "Gateway build input changed: $($inputFile.path). Rebuild and commit the gateway EXE and build receipt."
        }
    }
}

function Assert-GatewayBuild {
    param([Parameter(Mandatory = $true)] [string]$Root)
    $receiptPath = Join-Path $Root "runtime/gateway/build-manifest.json"
    $executable = Join-Path $Root "runtime/gateway/TianceRemoteGateway.exe"
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Gateway EXE or build receipt is missing. Run scripts/build-remote-gateway.ps1 and commit runtime/gateway."
    }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.schemaVersion -ne 1 -or $receipt.runtimeIdentifier -ne 'win-x64' -or
        $receipt.artifact.path -cne 'runtime/gateway/TianceRemoteGateway.exe' -or
        $receipt.artifact.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $receipt.sources -isnot [array]) {
        throw "Invalid gateway build receipt."
    }
    Assert-GatewayBuildInputs -Expected $receipt.sources -Actual @(Get-GatewayBuildInputs -Root $Root)
    $file = Get-Item -LiteralPath $executable
    if ($file.Length -ne $receipt.artifact.size -or
        (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant() -cne $receipt.artifact.sha256) {
        throw "Gateway EXE does not match its build receipt. Rebuild and commit runtime/gateway."
    }
    Write-Host "Gateway source and executable verified."
}
