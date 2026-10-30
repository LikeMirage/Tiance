# 发布包制作与 GitHub 发布流程

这份文档记录天策当前真实使用的 Windows 发布流程。目标是让 GitHub 标签、源码、前端编译产物和 `Tiance.zip` 始终对应同一个提交，不从开发者工作目录随手复制文件，也不把本地项目、密钥或缓存带进发布包。

这里只描述从源码确认到 GitHub Release 的完整链路。三种发布压缩包的文件白名单、清单和校验细节另见[《发布包与在线更新包制作流程》](18_发布包与在线更新包制作流程.md)；正式发布前的同结构试运行另见[《测试包制作与验证流程》](17_测试包制作与验证流程.md)。

## 当前发布包是什么

每个正式版本同时提供三个压缩包：

- `Tiance.zip` 是完整安装包，解压后可以直接启动；
- `Tiance-update.zip` 是可跳版本的完整程序更新包，不包含用户 `Data/`；
- `Tiance-update-incremental.zip` 是只供相邻版本使用的程序差分包。

它包含仓库已经正式跟踪的内容：

- FastAPI 后端源码；
- React 前端 `2_ReactWeb/dist` 最新生产构建；发布包不包含前端源码；
- PyWebView 桌面壳源码和根目录 `Tiance.exe`；
- 独立访问网关 `runtime/gateway/TianceRemoteGateway.exe`；
- 内置 Python 运行环境及后端、桌面壳运行依赖；
- 已公开的预置工具、供应商、主题、语言和对应设置文件；
- 许可证与 `system/` 内的版本、升级器文件。

它不会包含 Git 没有跟踪的本地状态：

- `.git` 版本库内部数据；
- `node_modules`、测试缓存、Python 缓存和构建临时文件；
- 本地项目、会话、数据库、日志和市场缓存；
- GitHub 登录信息、供应商凭证及其他私人密钥；
- `3_PyWebView/vendor/webview2-fixed` 固定 WebView2 环境。
- 根目录 `docs/`、`assets/` 和 `README.md`。

Windows 10/11 通常已经具有系统 WebView2 Runtime。当前发布包使用系统运行时，不额外携带固定 WebView2 环境。

## 发布原则

1. **只从已经提交的标签制作包。** `git archive` 读取标签对应的 Git 内容，不读取尚未提交的工作区修改。
   默认主题使用本机现有的 `Data/themes/theme-settings.json`；发布提交须包含当前选择及对应主题目录，再创建标签。打包会检查标签选择与本机一致且主题已纳入源码，不单独维护一份发布默认值。
2. **一个版本对应一个标签和一个 Release。** 发布后发现变化，应增加补丁版本，例如从 `0.3.0` 升到 `0.3.1`，不要把新包悄悄塞回旧标签。
3. **前端源码和编译产物同时更新。** 修改前端后必须重新构建并提交 `2_ReactWeb/dist`；发布包只取 `dist`。
4. **发布包使用明确白名单。** 完整包包含可运行程序与公开预置数据；更新包只包含程序文件。两者都不携带说明文档、宣传图片和 README。
5. **Release 附件名称保持简短。** 当前统一使用 `Tiance.zip`，避免 Windows 深层解压时放大路径长度问题。
6. **在线更新不得覆盖用户数据。** 差分更新包只能列出程序文件和删除清单；`Data` 下的所有内容全部由用户和各在线市场管理，更新包不得出现。
7. **版本号以 `system/version.json` 为运行时唯一来源。** 前端包、Python 包和 Windows 文件版本在发布时同步到同一版本，标签使用对应的 `vX.Y.Z`。

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

修改 `system/version.json`，并同步前端包、两个 Python 包和 Windows 启动器文件版本。发布版本 `X.Y.Z` 对应 Git 标签 `vX.Y.Z`。发布前必须确认这些版本一致。

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

`2_ReactWeb/dist/index.html` 和带摘要名称的资源文件发生变化是正常现象。日常原地构建保留旧摘要文件，以便已打开的窗口继续加载旧资源。正式发布需在独立输出目录执行干净构建，只把该目录中的产物加入发布提交；不要清空正在被开发窗口使用的 `dist`。例如执行 `pnpm exec vite build --outDir ../.codex_tmp/release-dist --emptyOutDir`，再核对、复制并暂存该产物集合；目标提交中应移除不属于本次构建的旧资源，工作目录仍可保留未跟踪的旧资源供打开中的窗口使用。

后端、桌面壳或工具发生变化时，还应运行对应测试。测试范围按本次改动决定，不能只因为前端构建成功就认为整个版本已经验证。

访问网关源码或构建配置发生变化时，提交前运行 `scripts/build-remote-gateway.ps1`，并将生成的 `runtime/gateway/TianceRemoteGateway.exe` 和 `runtime/gateway/build-manifest.json` 与源码一起提交。构建先在临时目录完成，编译失败不会删除现有网关。如果 EXE 被正在运行的天策占用，脚本会将运行中的文件保留到 `.codex_tmp/gateway-running`，再安装新文件，不终止进程；重启天策后才使用新文件。若系统连重命名也不允许，脚本停止，需正常退出天策再构建。

清单记录网关输入文件列表、每个文件的 SHA-256、EXE 的大小与 SHA-256，以及 SDK 和运行平台。源码摘要统一 CRLF/LF，排除 `bin/obj` 编译缓存。正式包和测试包都验证选定 Git 快照中的清单，源码增删改、构建脚本变化、EXE 被旧版覆盖或漏提交清单都会停止打包。校验不读取工作区中其他尚未提交的版本，也不为旧清单提供放行路径。

提交前可独立检查，不需要再次编译：

```powershell
. ./scripts/gateway-build-integrity.ps1
Assert-GatewayBuild -Root (Get-Location).Path
```

登录接口按实际连接来源 IP 限制每分钟最多 5 次（成功、失败均计入），并且全局最多同时执行 2 次登录验证，不排队。超限返回 HTTP 429、明确错误消息和 `Retry-After`。转发头不作为限流身份；反向代理后的请求会按代理连接地址合并计数。状态查询和普通会话请求不受登录限流影响。

网关限流回归测试：

```powershell
dotnet test 3_PyWebView/gateway/windows/TianceRemoteGateway.Tests/TianceRemoteGateway.Tests.csproj --configuration Release
```

需要 .NET 8 SDK；如果 SDK 安装在独立目录，用该目录下的 `dotnet.exe` 执行，构建脚本也可通过 `-DotnetPath` 指定。

## 三、提交正式版本

审查改动后提交并推送：

```powershell
git add -A
git commit -m "chore: release vX.Y.Z"
git push origin main
```

再次确认工作区干净，然后创建带说明的正式标签：

```powershell
git tag -a vX.Y.Z -m "Tiance vX.Y.Z"
git push origin vX.Y.Z
```

标签创建后不要移动。若内容还要变化，继续发布下一个补丁版本。

用户要求“先做发布包，不发布到远端”时，只进行本地提交、标签和打包，不执行推送及 GitHub Release 创建；获得后续授权后，再推送同一提交、标签及通过校验的附件。

## 四、制作完整安装包和在线更新包

从标签生成压缩包，而不是压缩当前目录。推荐使用仓库内脚本：

```powershell
./scripts/package-release.ps1 -Version <版本号> -Tag v<版本号> -PreviousTag v<上一版本号>
```

在线更新包使用文件级差分，只包含本次版本新增或修改的程序文件，并在包内写入删除清单。`system/update-manifest.json` 格式如下：

```json
{
  "schemaVersion": 2,
  "version": "0.3.11",
  "replace": ["system/version.json", "2_ReactWeb/dist/index.html"],
  "delete": ["2_ReactWeb/dist/assets/old-hash.js"]
}
```

更新器逐文件备份、替换和删除，失败时按同一清单回滚；禁止列入 `Data/`。

脚本会同时生成 `Tiance.zip`、`Tiance-update.zip`、`Tiance-update-incremental.zip` 和 `update.json`。

`update.json` 是软件校验更新包的发布合同。版本、文件名、大小和 SHA-256 任一项不一致，后端都会拒绝进入安装阶段。

完整安装包使用根目录 `runtime`，差分更新包只携带本次变化的程序文件。新发布规则从下一正式版本开始生效，用户 `Data/` 永不参与更新。

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
- WebView2 固定运行环境；
- 根目录 `docs/`、`assets/` 与 `README.md`。

还必须分别确认两个在线更新包：

- 包含 `system/update-manifest.json`、`system/version.json` 以及清单中列出的全部文件；
- 不包含任何 `Data/`、数据库、密钥或本地设置；
- 不包含 `.git`；
- 解压后的统一根目录仍为 `Tiance/`。

旧版 `3.10` 更新器有额外的核心文件检查，不能直接安装 `3.11` 的新协议差分包。旧版本迁移应使用完整安装包；从 `3.11` 开始，更新器按 `schemaVersion: 2` 的文件清单工作。

完整性检查应以标签经发布路径白名单、供应商白名单及 `.gitattributes` 的 `export-ignore` 过滤后的快照为准，压缩包只多一层统一的 `Tiance/` 根目录。供应商排序由白名单生成；不能直接拿整个标签文件集合与发布包比较。

## 五、创建 GitHub Release 并上传

维护者发布优先使用已登录的 GitHub CLI：

```powershell
gh auth login
gh auth status
gh release create vX.Y.Z `
  发布包/Tiance.zip `
  发布包/Tiance-update.zip `
  发布包/Tiance-update-incremental.zip `
  发布包/update.json `
  --repo LikeMirage/Tiance `
  --verify-tag `
  --title "Tiance vX.Y.Z"
```

也可以在 GitHub 网页的 Releases 页面选择已经推送的标签，手工上传同一个压缩包。软件内置的 `GitHub 发布` 工具是应用能力入口，不是维护者发布自己仓库的必要条件。无论使用哪种入口，都不能绕过前面的标签和内容校验。

## 六、发布后核对

发布完成后检查：

- GitHub 最新 Release 指向本次新标签；
- Release 标签最终指向本次提交；
- `Tiance.zip` 可以完整下载；
- `Tiance-update.zip`、`Tiance-update-incremental.zip` 与 `update.json` 可以完整下载；
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

完整安装包包含公开预置集合，不能直接覆盖已有 `Data`。软件内更新只能使用不含 `Data` 的 `Tiance-update.zip` 或 `Tiance-update-incremental.zip`；工具、主题和供应商继续由各自市场更新。

### 误以为源码或差分包会更新在线市场

源码仓库、软件 Release 和各类在线市场是三条独立发布链。`Data/` 不进入差分更新包；新增或修改工具、供应商后，还必须分别更新对应市场仓库并确认其构建工作流成功。
