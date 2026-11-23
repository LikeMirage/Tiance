# Run with Windows PowerShell -STA. Exercises the shipped helper without changing the system runtime.
param([switch]$VerifyMicrosoftDownload)
$ErrorActionPreference = "Stop"
$shellRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$binary = Join-Path $shellRoot "app/native/Tiance.WebViewCheck.exe"
$assembly = [Reflection.Assembly]::LoadFile($binary)
$flags = [Reflection.BindingFlags]'NonPublic, Static'
$check = $assembly.GetType("WebViewCheck")
$window = $assembly.GetType("SetupWindow")
$installer = $assembly.GetType("EvergreenInstaller")

function Assert-True($value, $message) { if (-not $value) { throw $message } }
function Test-Flow([bool[]]$answers, $browser, [bool]$failInstall, [bool]$success, [int]$installs) {
    $state = @{ i = 0; installs = 0; shown = 0 }
    $probe = [Func[Threading.Tasks.Task[bool]]]{
        $task = New-Object 'Threading.Tasks.TaskCompletionSource[bool]'
        $task.SetResult($answers[$state.i])
        $state.i++
        $task.Task
    }
    $install = [Func[Threading.Tasks.Task]]{
        $state.installs++
        if ($failInstall) { throw "offline" }
        [Threading.Tasks.Task]::CompletedTask
    }
    $progress = [Func[IDisposable]]{ $state.shown++; [IO.MemoryStream]::new() }
    $ok = $true
    try {
        $task = $check.GetMethod("EnsureCompatible", $flags).Invoke($null, [object[]]@($probe,$browser,$install,$progress))
        $task.GetAwaiter().GetResult() | Out-Null
    } catch { $ok = $false }
    Assert-True ($ok -eq $success -and $state.i -eq $answers.Length -and $state.installs -eq $installs -and $state.shown -eq $installs) "Unexpected startup flow: $($state | Out-String)"
}

Test-Flow @($true) $null $false $true 0
Test-Flow @($false,$true) $null $false $true 1
Test-Flow @($false,$false) $null $true $false 1
Test-Flow @($false,$false) $null $false $false 1
Test-Flow @($false,$true) $null $true $true 1
Test-Flow @($false) "fixed-runtime" $false $false 0
$compatible = $check.GetMethod("Compatible", $flags)
Assert-True ($compatible.Invoke($null, [object[]]@("146.0.3856.49"))) "Minimum release rejected"
Assert-True (-not $compatible.Invoke($null, [object[]]@("146.0.3856.48"))) "Outdated release accepted"
Assert-True (-not $compatible.Invoke($null, [object[]]@("158.0.1.1 beta"))) "Preview channel accepted"

$failure = $window.GetMethod("CreateFailure",$flags).Invoke($null,[object[]]@("test failure",$false))
try {
    $controls = $failure.Controls[0].Controls
    $address = @($controls | Where-Object { $_.AccessibleName -and $_.Text -like 'https://*' })
    Assert-True ($address.Count -eq 1 -and $address[0].ReadOnly -and $address[0].Text -eq $check.GetField("OfflineDownload",$flags).GetRawConstantValue()) "Offline download address missing"
    Assert-True ($controls[0].Text.Contains($check.GetField("Minimum",$flags).GetValue($null).ToString())) "Version missing"
    Assert-True ($null -ne $failure.AcceptButton) "Copy action missing"
} finally { $failure.Dispose() }

$verify = $installer.GetMethod("VerifyPublisher",$flags)
$rejected = $false
try { $verify.Invoke($null,[object[]][string[]]@($binary)) } catch { $rejected = $true }
Assert-True $rejected "Unsigned executable accepted"
if ($VerifyMicrosoftDownload) {
    $file = [IO.Path]::Combine([IO.Path]::GetTempPath(), "tiance-signer-" + [Guid]::NewGuid().ToString("N") + ".exe")
    try {
        $installer.GetMethod("Download",$flags).Invoke($null,[object[]][string[]]@($file))
        $hold = [IO.File]::Open($file,"Open","Read","Read")
        try { $verify.Invoke($null,[object[]][string[]]@($file)) } finally { $hold.Dispose() }
    } finally { [IO.File]::Delete($file) }
}
Write-Output "WebView prerequisite checks passed."
