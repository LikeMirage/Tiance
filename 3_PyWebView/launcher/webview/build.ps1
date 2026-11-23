[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$shellRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$sdk = Join-Path $shellRoot "../runtime/python-packages/desktop-shell/py313/site-packages/webview/lib/Microsoft.Web.WebView2.Core.dll"
$compiler = Join-Path $env:WINDIR "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
$outputDirectory = Join-Path $shellRoot "app/native"
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
$output = Join-Path $outputDirectory "Tiance.WebViewCheck.exe"
$sources = @("WebViewCheck.cs", "SetupWindow.cs", "EvergreenInstaller.cs") | ForEach-Object { Join-Path $PSScriptRoot $_ }
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 "/out:$output" "/reference:$sdk" `
    /reference:System.Net.Http.dll /reference:System.Windows.Forms.dll /reference:System.Drawing.dll $sources
if ($LASTEXITCODE -ne 0) { throw "Building WebViewCheck failed ($LASTEXITCODE)." }
