param(
    [string]$OutputDirectory = "测试包",
    [string[]]$WorkingTreePaths = @()
)

$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$output = Join-Path $root $OutputDirectory
$target = Join-Path $output "Tiance"
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("tiance-test-package-" + [guid]::NewGuid().ToString("N"))
$archive = Join-Path $work "source.tar"
$stage = Join-Path $work "Tiance"
$index = Join-Path $work "git-index"

if (-not (Test-Path -LiteralPath (Join-Path $root ".git") -PathType Container)) {
    throw "必须在 Tiance 源码仓库根目录运行测试包脚本。"
}
if (Test-Path -LiteralPath $target) {
    throw "测试包目录已存在：$target。请关闭其中正在运行的程序并移走旧目录后重试。"
}

New-Item -ItemType Directory -Force -Path $output, $stage | Out-Null
try {
    $treeish = "HEAD"
    if ($WorkingTreePaths.Count -gt 0) {
        $allowedRoots = @(
            "1_PythonServer",
            "2_ReactWeb\dist",
            "3_PyWebView",
            "Data\experience",
            "Data\knowledge",
            "Data\roles",
            "Data\themes",
            "Data\tools",
            "system",
            "Tiance.exe",
            "LICENSE"
        )
        $env:GIT_INDEX_FILE = $index
        try {
            & git read-tree HEAD
            if ($LASTEXITCODE -ne 0) {
                throw "无法创建测试包临时 Git 索引。"
            }
            foreach ($path in $WorkingTreePaths) {
                $normalized = ([string]$path).Replace("/", "\").Trim("\")
                if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized.Contains("..")) {
                    throw "测试包工作区路径无效：$path"
                }
                $allowed = $allowedRoots | Where-Object {
                    $normalized -eq $_ -or $normalized.StartsWith("$_\", [System.StringComparison]::OrdinalIgnoreCase)
                }
                if (-not $allowed) {
                    throw "测试包工作区路径不在允许范围：$path"
                }
                & git add -A -- $normalized
                if ($LASTEXITCODE -ne 0) {
                    throw "无法收集测试包工作区路径：$path"
                }
            }
            $treeish = (& git write-tree).Trim()
            if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($treeish)) {
                throw "无法生成测试包工作区快照。"
            }
        }
        finally {
            Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
        }
    }

    & git archive --format=tar --output=$archive $treeish -- `
        Tiance.exe LICENSE system runtime Data 1_PythonServer 2_ReactWeb/dist 3_PyWebView
    if ($LASTEXITCODE -ne 0) {
        throw "无法从当前提交提取测试包。"
    }

    tar -xf $archive -C $stage
    if ($LASTEXITCODE -ne 0) {
        throw "测试包解压失败。"
    }

    $requiredFiles = @(
        "Tiance.exe",
        "system/version.json",
        "1_PythonServer/run.py",
        "2_ReactWeb/dist/index.html",
        "3_PyWebView/run.py"
    )
    foreach ($relativePath in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $relativePath) -PathType Leaf)) {
            throw "测试包缺少必要文件：$relativePath"
        }
    }

    Move-Item -LiteralPath $stage -Destination $target
    $version = (Get-Content -LiteralPath (Join-Path $target "system/version.json") -Raw | ConvertFrom-Json).version
    $commit = (& git rev-parse --short HEAD).Trim()
    Write-Output "测试包：$target"
    Write-Output "源码提交：$commit"
    if ($WorkingTreePaths.Count -gt 0) {
        Write-Output "工作区快照：$($treeish.Substring(0, 12))（仅包含显式路径）"
    }
    Write-Output "程序版本：$version（测试包不修改版本号）"
} finally {
    Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
