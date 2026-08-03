# 发布包制作与 GitHub 发布流程

这份文档记录天策当前真实使用的 Windows 发布流程。目标是让 GitHub 标签、源码、前端编译产物和 `Tiance.zip` 始终对应同一个提交，不从开发者工作目录随手复制文件，也不把本地项目、密钥或缓存带进发布包。

## 当前发布包是什么

每个正式版本同时提供两个包：

- `Tiance.zip` 是完整安装包，解压后可以直接启动；
- `Tiance-update.zip` 是软件内更新包，只包含程序拥有的文件。

它包含仓库已经正式跟踪的内容：

- FastAPI 后端源码；
- React 前端源码与 `2_ReactWeb/dist` 最新生产构建；
- PyWebView 桌面壳源码和根目录 `Tiance.exe`；
- 内置 Python 运行环境及后端、桌面壳运行依赖；
- 已公开的预置工具、供应商、主题、语言和对应设置文件；
- README、许可证、文档和真实使用的图片资源。

它不会包含 Git 没有跟踪的本地状态：

- `.git` 版本库内部数据；
- `node_modules`、测试缓存、Python 缓存和构建临时文件；
- 本地项目、会话、数据库、日志和市场缓存；
- GitHub 登录信息、供应商凭证及其他私人密钥；
- `3_PyWebView/vendor/webview2-fixed` 固定 WebView2 环境。

Windows 10/11 通常已经具有系统 WebView2 Runtime。当前发布包使用系统运行时，不额外携带固定 WebView2 环境。

## 发布原则

1. **只从已经提交的标签制作包。** `git archive` 读取标签对应的 Git 内容，不读取尚未提交的工作区修改。
2. **一个版本对应一个标签和一个 Release。** 发布后发现变化，应增加补丁版本，例如从 `0.3.0` 升到 `0.3.1`，不要把新包悄悄塞回旧标签。
3. **前端源码和编译产物同时更新。** 修改前端后必须重新构建并提交 `2_ReactWeb/dist`。
4. **发布包不单独维护文件清单。** 哪些内容进入正式包，以仓库跟踪状态和 `.gitignore` 为准；修改这条边界时必须同时检查发布包。
5. **Release 附件名称保持简短。** 当前统一使用 `Tiance.zip`，避免 Windows 深层解压时放大路径长度问题。
6. **在线更新不得覆盖用户数据。** 更新包只能包含程序目录、桌面入口、内置运行环境和文档；根目录 `runtime` 属于程序；`Data` 下的所有内容全部由用户和各在线市场管理，更新包不得覆盖。
7. **版本号以根目录 `version.json` 为运行时唯一来源。** 前端包、Python 包和 Windows 文件版本在发布时同步到同一版本，标签使用对应的 `vX.Y.Z`。

## 一、发布前检查

在正式仓库根目录执行：

```powershell
git status --short
git branch --show-current
git pull --ff-only origin main
```

必须确认：

- 当前分支是 `main`；
- 工作区没有不明改动；
- 本地 `main` 已和远端同步；
- 本次版本号尚未被 GitHub 使用。

修改根目录 `version.json`，并同步前端包、两个 Python 包和 Windows 启动器文件版本。发布版本 `0.3.8` 对应 Git 标签 `v0.3.8`。发布前必须确认这些版本一致。

## 二、验证并构建前端

进入前端目录：

```powershell
cd 2_ReactWeb
pnpm install --frozen-lockfile
pnpm check
pnpm test:conversation-state
pnpm build
cd ..
```

构建完成后检查：

```powershell
git status --short
git diff --check
```

`2_ReactWeb/dist/index.html` 和带摘要名称的资源文件发生变化是正常现象。旧摘要文件应由构建过程移除，不能让新旧产物同时残留。

后端、桌面壳或工具发生变化时，还应运行对应测试。测试范围按本次改动决定，不能只因为前端构建成功就认为整个版本已经验证。

## 三、提交正式版本

审查改动后提交并推送：

```powershell
git add -A
git commit -m "chore: release v0.3.8"
git push origin main
```

再次确认工作区干净，然后创建带说明的正式标签：

```powershell
git tag -a v0.3.8 -m "Tiance v0.3.8"
git push origin v0.3.8
```

标签创建后不要移动。若内容还要变化，继续发布下一个补丁版本。

## 四、制作完整安装包和在线更新包

从标签生成压缩包，而不是压缩当前目录：

```powershell
New-Item -ItemType Directory -Force -Path "发布包" | Out-Null
git archive --format=zip --prefix=Tiance/ -o "发布包/Tiance.zip" v<版本号>
Get-FileHash "发布包/Tiance.zip" -Algorithm SHA256
```

在线更新包只归档下列程序文件：

```powershell
git archive --format=zip --prefix=Tiance/ -o "发布包/Tiance-update.zip" v<版本号> -- `
  version.json Tiance.exe TianceUpdater.exe LICENSE README.md `
  1_PythonServer 2_ReactWeb 3_PyWebView assets docs runtime

$updateFile = Get-Item "发布包/Tiance-update.zip"
$updateHash = (Get-FileHash $updateFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
@{
  schemaVersion = 1
  version = "<版本号>"
  assetName = "Tiance-update.zip"
  sha256 = $updateHash
  size = $updateFile.Length
} | ConvertTo-Json | Set-Content "发布包/update.json" -Encoding utf8
```

`update.json` 是软件校验更新包的发布合同。版本、文件名、大小和 SHA-256 任一项不一致，后端都会拒绝进入安装阶段。

完整安装包始终直接使用根目录 `runtime`。为兼容仍在使用 `v0.3.7` 的客户端，在线更新包暂时把标签中的根目录 `runtime` 映射为包内 `Data/runtime`：旧更新器会先放入旧位置，新启动器会迁移到根目录；`v0.3.8` 及以后更新器会直接把这份桥接载荷替换到根目录 `runtime`。这不是用户数据覆盖，更新包不得包含 `Data/runtime` 以外的任何 `Data` 文件。待停止支持 `v0.3.7` 后，更新包再恢复为根目录 `runtime`。

`发布包` 目录本身被 `.gitignore` 排除，压缩包不会再次进入源码仓库。

建议至少检查以下结构：

```powershell
tar -tf "发布包/Tiance.zip" | Select-Object -First 30
tar -tf "发布包/Tiance.zip" | Select-String -Pattern "Tiance.exe|2_ReactWeb/dist/index.html|Data/providers|Data/themes|Data/tools"
```

还要确认包中没有：

- `Tiance/.git/`；
- `node_modules`、`__pycache__` 或 `.pyc`；
- `Data/secrets`、`Data/projects`、数据库或日志；
- 供应商 `credentials.json`；
- WebView2 固定运行环境。

还必须单独确认 `Tiance-update.zip`：

- 包含 `TianceUpdater.exe`、前端 `dist`，运行环境桥接载荷仅可位于 `Data/runtime`；
- 不包含 `Data/projects`、`Data/tools`、`Data/themes`、`Data/providers`、数据库、密钥或本地设置；
- 不包含 `.git`；
- 解压后的统一根目录仍为 `Tiance/`。

最严格的完整性检查是：压缩包中的文件集合应与该标签的 `git ls-tree -r --name-only v<版本号>` 一致，只多一层统一的 `Tiance/` 根目录。

## 五、创建 GitHub Release 并上传

可以使用天策内置的 `GitHub 发布` 工具完成，不要求安装 GitHub CLI：

1. 在设定集登录 GitHub，并确认 Tiance Desktop 对该仓库具有 Contents 读写权限。
2. 调用 `GitHub 发布` 工具创建 Release：仓库为 `LikeMirage/Tiance`，标签为 `v0.3.8`，名称为 `Tiance v0.3.8`。
3. 填写本版本真实完成的修复和变化，不把未来计划写成已完成功能。
4. 使用同一工具上传 `发布包/Tiance.zip`、`发布包/Tiance-update.zip` 和 `发布包/update.json`。
5. 打开 GitHub Release 页面，确认标签、发布时间、附件名称和附件大小正确。

也可以在 GitHub 网页的 Releases 页面选择已经推送的标签，手工上传同一个压缩包。无论使用哪种入口，都不能绕过前面的标签和内容校验。

## 六、发布后核对

发布完成后检查：

- GitHub 最新 Release 指向本次新标签；
- Release 标签最终指向本次提交；
- `Tiance.zip` 可以完整下载；
- `Tiance-update.zip` 与 `update.json` 可以完整下载；
- 下载文件大小与本地包一致；
- GitHub 返回附件摘要时，其 SHA-256 与本地 `Get-FileHash` 结果一致；
- 在一个新的短目录中解压后，能够从根目录启动 `Tiance.exe`；
- 软件加载的是压缩包内最新前端，而不是开发机上仍在运行的前端开发服务器。
- 从旧发布版进入“设定集 → 软件更新”，能够识别新版本、下载、退出、替换并重新启动；更新后用户数据仍然存在。

至少进行一次干净启动检查。不要在原开发目录直接验证发布包，否则本地缓存、开发服务和已有数据可能掩盖缺件。

## 七、常见错误

### 修改了源码，却没有更新 `dist`

用户运行发布包时读取的是 `2_ReactWeb/dist`，不会现场编译 React 源码。源码更新而 `dist` 未更新，会造成“仓库里已经修了，软件界面仍是旧版”。

### 从工作目录直接压缩

直接压缩文件夹会把未提交修改、缓存、密钥、旧构建文件甚至整个 `.git` 一起带入。正式包必须由 `git archive` 从标签生成。

### 用新包覆盖旧 Release

这会让同一个版本号在不同时间代表不同内容，用户无法判断自己拿到的是哪一份。修复应发布新的补丁版本。

### 只上传 ZIP，没有推送标签

Release 附件将失去可核对的源码基线。正确顺序是先提交、推送、创建标签，再从该标签生成并上传附件。

### 只移动 `Tiance.exe`

`Tiance.exe` 是入口，不是单文件程序。后端、桌面壳、前端产物和内置 Python 都依赖完整目录结构；给用户制作快捷方式时，应让快捷方式指向解压目录中的 EXE。

### 把完整安装包直接当更新包

完整包包含公开预置集合，不能直接覆盖已有 `Data`。软件内更新必须使用受限的 `Tiance-update.zip`；工具、主题和供应商继续由各自市场更新。
