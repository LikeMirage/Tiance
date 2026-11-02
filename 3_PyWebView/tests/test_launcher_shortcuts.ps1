# Run with Windows PowerShell after launcher/windows/build.ps1.
# Exercises Shell Link persistence without starting Tiance or altering real shortcuts.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$launcherPath = Join-Path $projectRoot 'Tiance.exe'
$iconPath = Join-Path $projectRoot '3_PyWebView\assets\app-icon.ico'
$launcherType = [Reflection.Assembly]::LoadFile($launcherPath).GetType('TianceLauncher')
$methodFlags = [Reflection.BindingFlags]'Static,NonPublic'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('tiance-shortcut-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$shortcutPath = Join-Path $testRoot 'Tiance-test.lnk'
$shell = New-Object -ComObject WScript.Shell

$launcherType.GetMethod('CreateOrUpdateShortcut', $methodFlags).Invoke($null, [object[]][string[]]@($shortcutPath, $launcherPath, $projectRoot)) | Out-Null
$shortcut = $shell.CreateShortcut($shortcutPath)
if ($shortcut.IconLocation -ne ($iconPath + ',0')) { throw 'New shortcut did not use the shared icon.' }
if ($shortcut.TargetPath -ne $launcherPath) { throw 'New shortcut target changed.' }

$shortcut.Arguments = '--keep-existing-argument'
$shortcut.WorkingDirectory = $testRoot
$shortcut.Description = 'Keep custom description'
$shortcut.IconLocation = $launcherPath + ',0'
$shortcut.Save()
$launcherType.GetMethod('UpdateShortcutIdentity', $methodFlags).Invoke($null, [object[]][string[]]@($shortcutPath, $iconPath)) | Out-Null
$updated = $shell.CreateShortcut($shortcutPath)
if ($updated.IconLocation -ne ($iconPath + ',0')) { throw 'Existing shortcut icon was not updated.' }
if ($updated.TargetPath -ne $launcherPath -or $updated.Arguments -ne '--keep-existing-argument' -or
    $updated.WorkingDirectory -ne $testRoot -or $updated.Description -ne 'Keep custom description') {
    throw 'Icon update changed unrelated shortcut settings.'
}
$matches = $launcherType.GetMethod('ShortcutTargets', $methodFlags)
if (-not $matches.Invoke($null, [object[]][string[]]@($shortcutPath, $launcherPath))) { throw 'Own shortcut was not recognized.' }
if ($matches.Invoke($null, [object[]][string[]]@($shortcutPath, (Join-Path $testRoot 'other.exe')))) { throw 'Unrelated shortcut matched.' }
$shellApp = New-Object -ComObject Shell.Application
$linkItem = $shellApp.NameSpace($testRoot).ParseName('Tiance-test.lnk')
if ($linkItem.ExtendedProperty('System.AppUserModel.ID') -ne 'LikeMirage.Tiance') { throw 'Application identity was not preserved.' }
Write-Output 'PASS: new and existing icon, application identity, target/arguments/directory/description preserved.'
