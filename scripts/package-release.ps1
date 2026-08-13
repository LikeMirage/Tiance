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
$incrementalTree = Join-Path $work "incremental"
$fullProgramTree = Join-Path $work "full-program"

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

function Copy-ProgramFile([string]$RelativePath, [string]$DestinationTree) {
    $source = Join-Path $currentTree $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "标签中找不到文件：$RelativePath"
    }
    $destination = Join-Path $DestinationTree ("Tiance/" + $RelativePath)
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

function Write-UpdateManifest(
    [string]$DestinationTree,
    [string[]]$ReplacePaths,
    [string[]]$DeletePaths,
    [string]$Mode
) {
    $manifest = [ordered]@{
        schemaVersion = 2
        version = $Version
        mode = $Mode
        replace = @($ReplacePaths)
        delete = @($DeletePaths)
    }
    $manifestPath = Join-Path $DestinationTree "Tiance/system/update-manifest.json"
    New-Item -ItemType Directory -Force -Path (Split-Path $manifestPath) | Out-Null
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
}

function Get-PackageMetadata([string]$Path, [string]$AssetName) {
    $file = Get-Item -LiteralPath $Path
    return [ordered]@{
        assetName = $AssetName
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $file.Length
    }
}

New-Item -ItemType Directory -Force -Path $output, $currentTree, $incrementalTree, $fullProgramTree | Out-Null
try {
    Invoke-Git @("archive", "--format=tar", "--output=$work/current.tar", $Tag)
    tar -xf (Join-Path $work "current.tar") -C $currentTree
    if ($LASTEXITCODE -ne 0) { throw "无法解压发布标签。" }

    $versionPayload = Get-Content -LiteralPath (Join-Path $currentTree "system/version.json") -Raw | ConvertFrom-Json
    if ($versionPayload.version -ne $Version) {
        throw "标签版本号 $($versionPayload.version) 与发布版本 $Version 不一致。"
    }

    # 完整安装包包含公开预置数据；两个在线更新包始终不包含 Data。
    $fullInstall = Join-Path $output "Tiance.zip"
    Invoke-Git @(
        "archive", "--format=zip", "--prefix=Tiance/", "--output=$fullInstall", $Tag, "--",
        "Tiance.exe", "LICENSE", "system", "runtime", "Data", "1_PythonServer", "2_ReactWeb/dist", "3_PyWebView"
    )

    # 相邻版本增量包：只包含 PreviousTag -> Tag 之间变化的程序文件。
    $incrementalReplace = [System.Collections.Generic.List[string]]::new()
    $incrementalDelete = [System.Collections.Generic.List[string]]::new()
    $changes = @(git diff --name-status --find-renames $PreviousTag $Tag --)
    if ($LASTEXITCODE -ne 0) { throw "无法计算相邻版本差异。" }
    foreach ($line in $changes) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parts = $line -split "`t"
        $status = $parts[0]
        if ($status.StartsWith("R") -or $status.StartsWith("C")) {
            if ($parts.Count -lt 3) { throw "无法解析 Git 重命名记录：$line" }
            if ($status.StartsWith("R") -and (Test-AllowedPath $parts[1])) {
                $incrementalDelete.Add($parts[1])
            }
            $candidate = $parts[2]
        } else {
            if ($parts.Count -lt 2) { throw "无法解析 Git 变更记录：$line" }
            $candidate = $parts[1]
        }
        if ($status.StartsWith("D")) {
            if (Test-AllowedPath $candidate) { $incrementalDelete.Add($candidate) }
            continue
        }
        if (-not (Test-AllowedPath $candidate)) { continue }
        Copy-ProgramFile $candidate $incrementalTree
        $incrementalReplace.Add($candidate)
    }
    if (-not $incrementalReplace.Contains("system/version.json")) {
        Copy-ProgramFile "system/version.json" $incrementalTree
        $incrementalReplace.Add("system/version.json")
    }
    $incrementalReplacePaths = @($incrementalReplace | Sort-Object -Unique)
    $incrementalDeletePaths = @($incrementalDelete | Sort-Object -Unique)
    Write-UpdateManifest $incrementalTree $incrementalReplacePaths $incrementalDeletePaths "incremental"

    # 跳版本完整程序包：携带目标标签的全部程序文件，并删除历史正式版本中已淘汰的程序文件。
    $currentProgramPaths = @(
        git ls-tree -r --name-only $Tag -- | Where-Object { Test-AllowedPath $_ } | Sort-Object -Unique
    )
    if ($LASTEXITCODE -ne 0 -or $currentProgramPaths.Count -eq 0) {
        throw "无法读取目标标签程序文件。"
    }
    foreach ($path in $currentProgramPaths) {
        Copy-ProgramFile $path $fullProgramTree
    }
    $historicalProgramPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($releaseTag in @(git tag --list "v*")) {
        foreach ($path in @(git ls-tree -r --name-only $releaseTag --)) {
            if (Test-AllowedPath $path) { [void]$historicalProgramPaths.Add($path) }
        }
    }
    $currentProgramPathSet = [System.Collections.Generic.HashSet[string]]::new(
        [string[]]$currentProgramPaths,
        [System.StringComparer]::Ordinal
    )
    $fullDeletePaths = @(
        $historicalProgramPaths | Where-Object { -not $currentProgramPathSet.Contains($_) } | Sort-Object
    )
    Write-UpdateManifest $fullProgramTree $currentProgramPaths $fullDeletePaths "full"

    $fullUpdate = Join-Path $output "Tiance-update.zip"
    $incrementalUpdate = Join-Path $output "Tiance-update-incremental.zip"
    Compress-Archive -Path (Join-Path $fullProgramTree "Tiance") -DestinationPath $fullUpdate -Force
    Compress-Archive -Path (Join-Path $incrementalTree "Tiance") -DestinationPath $incrementalUpdate -Force

    $fullMetadata = Get-PackageMetadata $fullUpdate "Tiance-update.zip"
    $incrementalMetadata = Get-PackageMetadata $incrementalUpdate "Tiance-update-incremental.zip"
    $incrementalMetadata["fromVersion"] = $PreviousTag.TrimStart("v")
    [ordered]@{
        # 顶层字段保留给旧客户端；旧客户端始终下载可跳版本的完整程序包。
        schemaVersion = 1
        version = $Version
        assetName = $fullMetadata.assetName
        sha256 = $fullMetadata.sha256
        size = $fullMetadata.size
        full = $fullMetadata
        incremental = $incrementalMetadata
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output "update.json") -Encoding utf8

    Write-Output "完整安装包：$fullInstall"
    Write-Output "跳版本程序包：$fullUpdate"
    Write-Output "相邻增量包：$incrementalUpdate"
    Write-Output "增量替换：$($incrementalReplacePaths.Count)，增量删除：$($incrementalDeletePaths.Count)"
    Write-Output "完整替换：$($currentProgramPaths.Count)，历史删除：$($fullDeletePaths.Count)"
} finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
