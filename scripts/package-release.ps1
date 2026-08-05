param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [Parameter(Mandatory = $true)] [string]$Tag,
    [Parameter(Mandatory = $true)] [string]$PreviousTag,
    [string]$OutputDirectory = "发布包"
)

$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$output = Join-Path $root $OutputDirectory
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("tiance-release-" + [guid]::NewGuid().ToString("N"))
$currentTree = Join-Path $work "current"
$updateTree = Join-Path $work "update"

function Invoke-Git([string[]]$Arguments) {
    & git @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git 命令失败：$($Arguments -join ' ')" }
}

function Test-AllowedPath([string]$Path) {
    return $Path -eq "Tiance.exe" -or $Path -eq "LICENSE" -or
        $Path.StartsWith("system/") -or $Path.StartsWith("runtime/") -or
        $Path.StartsWith("1_PythonServer/") -or $Path.StartsWith("3_PyWebView/") -or
        $Path.StartsWith("2_ReactWeb/dist/")
}

New-Item -ItemType Directory -Force -Path $output, $currentTree, $updateTree | Out-Null
Invoke-Git @("archive", "--format=tar", "--output=$work/current.tar", $Tag)
tar -xf (Join-Path $work "current.tar") -C $currentTree
$tagRoot = $currentTree

# 完整包只包含公开运行内容，前端只取 dist。
$full = Join-Path $output "Tiance.zip"
Invoke-Git @("archive", "--format=zip", "--prefix=Tiance/", "--output=$full", $Tag, "--", "Tiance.exe", "LICENSE", "system", "runtime", "Data", "1_PythonServer", "2_ReactWeb/dist", "3_PyWebView")

$replace = [System.Collections.Generic.List[string]]::new()
$delete = [System.Collections.Generic.List[string]]::new()
$changes = @(git diff --name-status --find-renames $PreviousTag $Tag --)
foreach ($line in $changes) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line -split "`t"
    $status = $parts[0]
    $paths = if ($status.StartsWith("R") -or $status.StartsWith("C")) { @($parts[1], $parts[2]) } else { @($parts[1]) }
    if ($status.StartsWith("R")) { $delete.Add($paths[0]) }
    $candidate = $paths[-1]
    if ($status.StartsWith("D")) { $delete.Add($candidate); continue }
    if (-not (Test-AllowedPath $candidate)) { continue }
    $source = Join-Path $tagRoot $candidate
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "标签中找不到文件：$candidate" }
    $destination = Join-Path $updateTree ("Tiance/" + $candidate)
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    $replace.Add($candidate)
}

if (-not $replace.Contains("system/version.json")) {
    $versionSource = Join-Path $tagRoot "system/version.json"
    $versionDestination = Join-Path $updateTree "Tiance/system/version.json"
    New-Item -ItemType Directory -Force -Path (Split-Path $versionDestination) | Out-Null
    Copy-Item -LiteralPath $versionSource -Destination $versionDestination -Force
    $replace.Add("system/version.json")
}
$manifest = [ordered]@{ schemaVersion = 2; version = $Version; replace = @($replace | Sort-Object -Unique); delete = @($delete | Where-Object { Test-AllowedPath $_ } | Sort-Object -Unique) }
$manifestPath = Join-Path $updateTree "Tiance/system/update-manifest.json"
New-Item -ItemType Directory -Force -Path (Split-Path $manifestPath) | Out-Null
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8

$update = Join-Path $output "Tiance-update.zip"
Compress-Archive -Path (Join-Path $updateTree "Tiance") -DestinationPath $update -Force
$file = Get-Item -LiteralPath $update
$hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{ schemaVersion = 1; version = $Version; assetName = "Tiance-update.zip"; sha256 = $hash; size = $file.Length } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output "update.json") -Encoding utf8

Write-Output "完整包：$full"
Write-Output "差分包：$update"
Write-Output "替换文件：$($replace.Count)，删除文件：$($delete.Count)"
