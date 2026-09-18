# Build a package-only Git tree. Never edit the working tree or the real index.
function New-PackageProviderTree {
    param(
        [Parameter(Mandatory = $true)] [string]$Treeish,
        [Parameter(Mandatory = $true)] [string]$TemporaryDirectory
    )

    $policyText = & git show "${Treeish}:scripts/package-providers.json"
    if ($LASTEXITCODE -ne 0) { throw "Package provider allowlist is missing from the selected snapshot." }
    $policy = ($policyText -join "`n") | ConvertFrom-Json
    if ($policy.schemaVersion -ne 1 -or $policy.providerIds -isnot [array]) {
        throw "Invalid package provider allowlist."
    }
    $providerIds = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($providerId in $policy.providerIds) {
        if ($providerId -isnot [string] -or $providerId -cnotmatch '^[a-z0-9][a-z0-9_-]*$' -or
            -not $providerIds.Add($providerId)) {
            throw "Package provider IDs must be unique lowercase directory names."
        }
    }
    # Same public files as a provider-market package; credentials/caches never qualify.
    $publicFiles = @("manifest.json", "provider.json", "provider-rules.json", "model-rules.json", "models.json")
    $allowedPaths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    [void]$allowedPaths.Add("Data/providers/provider-settings.json")
    foreach ($providerId in $policy.providerIds) {
        foreach ($fileName in $publicFiles) {
            [void]$allowedPaths.Add("Data/providers/$providerId/$fileName")
        }
    }

    $entries = @(& git -c core.quotePath=false ls-tree -r $Treeish -- Data/providers)
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect providers in the selected snapshot." }
    $present = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $excluded = [System.Collections.Generic.List[string]]::new()
    foreach ($entry in $entries) {
        $parts = $entry -split "`t", 2
        if ($parts.Count -ne 2) { throw "Invalid Git provider entry." }
        $path = $parts[1]
        if ($path.StartsWith('"')) { throw "Provider paths with control characters cannot be packaged." }
        if ($allowedPaths.Contains($path)) {
            if ($parts[0] -notmatch '^100(644|755) blob ') {
                throw "Public provider data must be regular files: $path"
            }
            [void]$present.Add($path)
        } else {
            $excluded.Add($path)
        }
    }
    foreach ($path in $allowedPaths) {
        if (-not $present.Contains($path)) { throw "Allowlisted provider file is missing: $path" }
    }

    $settingsText = & git show "${Treeish}:Data/providers/provider-settings.json"
    if ($LASTEXITCODE -ne 0) { throw "Provider settings are missing from the selected snapshot." }
    $settings = ($settingsText -join "`n") | ConvertFrom-Json
    if ($settings.schemaVersion -ne 1 -or $null -eq $settings.PSObject.Properties["providerOrder"]) {
        throw "Invalid provider settings in the selected snapshot."
    }
    # Package order comes from the public policy, never the developer's local selection.
    $settings.providerOrder = @($policy.providerIds)
    $settingsPath = Join-Path $TemporaryDirectory "package-provider-settings.json"
    [IO.File]::WriteAllText(
        $settingsPath, ($settings | ConvertTo-Json -Depth 100), [Text.UTF8Encoding]::new($false)
    )

    $previousIndex = $env:GIT_INDEX_FILE
    $packageIndex = Join-Path $TemporaryDirectory "package-provider-index"
    if (Test-Path -LiteralPath $packageIndex) { throw "Package provider index already exists." }
    try {
        $env:GIT_INDEX_FILE = $packageIndex
        & git read-tree $Treeish
        if ($LASTEXITCODE -ne 0) { throw "Cannot create the package provider index." }
        foreach ($path in $excluded) {
            & git update-index --force-remove -- $path
            if ($LASTEXITCODE -ne 0) { throw "Cannot exclude local provider files." }
        }
        $settingsBlob = & git hash-object -w -- $settingsPath
        if ($LASTEXITCODE -ne 0) { throw "Cannot store the public provider settings." }
        & git update-index --add --cacheinfo "100644,$settingsBlob,Data/providers/provider-settings.json"
        if ($LASTEXITCODE -ne 0) { throw "Cannot include the public provider settings." }
        $packageTree = & git write-tree
        if ($LASTEXITCODE -ne 0) { throw "Cannot write the package provider tree." }
        $packagedPaths = @(& git -c core.quotePath=false ls-tree -r --name-only $packageTree -- Data/providers)
        if ($LASTEXITCODE -ne 0 -or $packagedPaths.Count -ne $allowedPaths.Count) {
            throw "Package provider file verification failed."
        }
        foreach ($path in $packagedPaths) {
            if (-not $allowedPaths.Contains($path)) { throw "An excluded provider file remains in the package tree." }
        }
        Write-Host "Package providers: $($policy.providerIds -join ', '); excluded files: $($excluded.Count)"
        return $packageTree.Trim()
    } finally {
        if ($null -eq $previousIndex) {
            Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
        } else {
            $env:GIT_INDEX_FILE = $previousIndex
        }
    }
}
