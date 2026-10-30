# The normal local theme setting is also the release default. No second config.
function Assert-PackageThemeSelection {
    param([Parameter(Mandatory = $true)] [string]$Treeish)

    $settingsPath = "Data/themes/theme-settings.json"
    $localSettings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($localSettings.schemaVersion -ne 1 -or
        $localSettings.activeThemeId -isnot [string] -or
        $localSettings.activeThemeId -cnotmatch '^[a-z0-9][a-z0-9-]{0,63}$') {
        throw "Invalid local theme selection: $settingsPath"
    }

    $snapshotText = & git show "${Treeish}:$settingsPath"
    if ($LASTEXITCODE -ne 0) { throw "Theme settings are missing from the package snapshot. Include $settingsPath in the release commit or test snapshot." }
    $snapshotSettings = ($snapshotText -join "`n") | ConvertFrom-Json
    if ($snapshotSettings.schemaVersion -ne 1 -or
        $snapshotSettings.activeThemeId -cne $localSettings.activeThemeId) {
        throw "Package theme selection differs from the local selection. Include $settingsPath in the release commit or test snapshot before packaging."
    }

    $themeId = $localSettings.activeThemeId
    $themePath = "Data/themes/$themeId/theme.json"
    $themeText = & git show "${Treeish}:$themePath"
    if ($LASTEXITCODE -ne 0) { throw "Selected theme is missing from the package snapshot: $themePath. Include the theme in the release commit or test snapshot." }
    $theme = ($themeText -join "`n") | ConvertFrom-Json
    if ($theme.schemaVersion -ne 2 -or $theme.id -cne $themeId) {
        throw "Selected theme definition does not match the package selection: $themePath"
    }
    Write-Host "Package default theme: $themeId (current local selection)"
}
