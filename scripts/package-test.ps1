param(
    [string]$OutputDirectory = "测试包"
)

$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$output = Join-Path $root $OutputDirectory
$target = Join-Path $output "Tiance"
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("tiance-test-package-" + [guid]::NewGuid().ToString("N"))
$archive = Join-Path $work "source.tar"
$stage = Join-Path $work "Tiance"

if (-not (Test-Path -LiteralPath (Join-Path $root ".git") -PathType Container)) {
    throw "必须在 Tiance 源码仓库根目录运行测试包脚本。"
}
if (Test-Path -LiteralPath $target) {
    throw "测试包目录已存在：$target。请关闭其中正在运行的程序并移走旧目录后重试。"
}

New-Item -ItemType Directory -Force -Path $output, $stage | Out-Null
try {
    & git archive --format=tar --output=$archive HEAD -- `
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
    Write-Output "程序版本：$version（测试包不修改版本号）"
} finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
