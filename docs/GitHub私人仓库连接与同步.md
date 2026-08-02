# 天策连接 GitHub 私人仓库：授权、市场与多地同步

本文记录天策当前已经实现的 GitHub 私人仓库方案，也解释最容易混淆的两种用法：把私人仓库作为“在线市场”，以及把本地某一集完整同步到私人仓库。

天策通过 GitHub API 读写仓库，不要求用户安装 Git、GitHub Desktop 或其他命令行软件。登录凭据、仓库授权和同步绑定都由天策管理，真正提交前必须先生成差异计划，由用户确认后才执行。

## 1. 先分清两种仓库用途

### 1.1 在线市场仓库

在线市场用于“浏览并选择单个内容下载”。例如从主题市场下载一个主题，或者从工具市场下载一个工具。

它必须在读取入口下提供 `index.json`。`index.json` 是市场目录，负责列出可下载项目、版本、作者、简介、安装包位置和完整性信息。每个可下载项目内部再使用 `manifest.json` 声明自己的身份和版本。

公开市场通常通过 GitHub Pages 发布，地址类似：

```text
https://likemirage.github.io/Tiance-themes
```

私人市场不能使用公开 Pages 暴露内容，直接填写仓库地址：

```text
https://github.com/your-name/your-private-market
```

天策会使用已经登录的 GitHub 身份从私人仓库读取 `index.json` 和安装包。

### 1.2 集合同步仓库

集合同步用于“把本地一整集保存到 GitHub，再在另一台设备拉取”。当前支持：

- 项目集
- 知识集
- 经验集
- 角色集
- 主题集
- 工具集
- 供应商集

同步仓库不要求 `index.json`。天策直接比较本地集合根目录与绑定的远端目录，并同步 `catalog.json`、项目文件夹以及其他本地状态文件。

普通项目集还有一条专用通路：当私人 GitHub 仓库没有市场 `index.json` 时，“在线项目”会改读同步产生的 `catalog.json`，把每个项目目录转换成可单独下载的项目。刚初始化、尚未提交项目数据的空仓库会显示 0 个项目，不再作为连接错误。这样同一个 `self-projects` 仓库既能整集同步，也能按项目拉取，无需复制公共市场结构或手工维护索引。其他类型的在线市场仍然要求正式 `index.json`。

## 2. GitHub App 从一开始就应当设置为可读写

天策的私人仓库目标是备份、多地同步和由 AI 协助提交，仅有读取权限不能完成这些工作。因此创建或修改 GitHub App 时，仓库权限应当直接设置为：

```text
Repository permissions
└─ Contents: Read and write
```

`Metadata` 的只读权限由 GitHub 自动提供。只有确实要修改 `.github/workflows/` 下工作流文件时，才需要另外评估工作流相关权限；普通天策集合同步不需要为了“以后可能用到”而扩大授权。

修改 GitHub App 权限后，还要回到该 App 的安装页面确认新的权限。只在 App 设置页把 `Contents` 改成可读写，并不一定会让已有安装立刻获得写权限。

推荐安装时选择 `Only select repositories`，只把专门用于天策的私人仓库授权给 Tiance Desktop。需要新增仓库时，再从天策“设定集 → GitHub 登录 → 添加或移除仓库”进入 GitHub 安装管理页。

## 3. 登录和授权步骤

1. 在天策打开“设定集 → GitHub 登录”。
2. 点击登录，浏览器会打开 GitHub 的设备授权页。
3. 按页面提示确认登录。
4. 安装 Tiance Desktop GitHub App，并选择允许访问的仓库。
5. 确认 `Contents` 权限为 `Read and write`。
6. 回到天策点击“刷新”。仓库列表会同时显示“私人/公开”和“可读写/只读”。

刷新只重新读取 GitHub 当前授权，不会提交或拉取任何文件。若授权页面刚刚发生变化，GitHub 偶尔需要短暂时间更新安装状态；刷新后仍显示只读时，应先检查 App 安装是否已经接受新权限，再重新登录。

## 4. 在某一集中绑定同步仓库

每个在线看板顶部都有“同步”入口。绑定时需要填写：

- 仓库：从已经授权的仓库中选择。
- 分支：通常使用仓库默认分支 `main`。
- 仓库内目录：留空表示使用仓库根目录；也可以填写 `projects`、`themes` 等子目录。

绑定信息保存在：

```text
Data/secrets/github-sync-settings.json
```

GitHub 登录凭据加密保存在：

```text
Data/secrets/github-auth.json
```

这两个文件不属于任何一个集合，也不会随集合同步到 GitHub。退出 GitHub 登录会删除本地登录凭据；解除某一集的绑定只删除该集的同步设置，不会删除本地文件或远端仓库。

### 推荐：一集一个仓库

最清楚的方案是每一集使用一个私人仓库，例如：

```text
tiance-projects-private
tiance-knowledge-private
tiance-experience-private
tiance-roles-private
tiance-themes-private
tiance-tools-private
tiance-providers-private
```

也可以共用一个仓库，但必须为每一集填写不同的“仓库内目录”：

```text
projects/
knowledge/
experience/
roles/
themes/
tools/
providers/
```

不能把两个集合绑定到同一个远端目录。同步把绑定目录视为该集的完整镜像；如果两个集合共用同一路径，一个集合提交时可能把另一个集合的文件判断为应删除内容。

## 5. 安全同步流程

天策不把“拉取”和“提交”做成立即执行按钮，而是分成两步。

### 5.1 检查拉取

“检查拉取”比较远端与本地，生成将要新增、更新和删除的本地文件列表。此时不会改动文件。确认差异后再执行拉取。

真正拉取时，天策先把远端文件下载到临时目录，并为将被覆盖的文件建立临时备份。全部准备完成后才替换本地文件；中途失败会尝试恢复已改动内容。

### 5.2 检查提交

“检查提交”比较本地与远端，生成将要写入 GitHub 的差异列表。此时不会创建提交。确认后，天策通过 GitHub API 创建文件对象和一次完整提交，再更新远端分支。

天策不会强制覆盖已经变化的远端分支。如果生成计划后，本地文件、仓库绑定或远端版本发生变化，原计划会失效，必须重新检查差异。

### 5.3 空仓库

空仓库可以直接作为同步目标。第一次提交时必须使用仓库默认分支，天策会完成必要初始化，再把集合内容放入一次正式提交。

### 5.4 不参与同步的本地临时内容

以下内容不是稳定的跨设备数据，不进入集合快照：

- `.git/`
- `.cache/`、`.codex_tmp/`、`.market-cache/`、`.pytest_cache/`、`.trash/`
- `.venv/`、`venv/`、`node_modules/`、`dependencies/`、`__pycache__/`
- Microsoft Office 打开文件时产生的 `~$...` 锁文件
- GitHub 仓库同步工具自身的 `program/config.json`

`.Tiance/` 不在排除列表中。它包含会话、分支、记忆和项目状态，正是项目跨设备恢复的重要组成部分。

## 6. 七类集合的同步结构

以下结构描述的是“整集同步仓库”，不是在线市场发布目录。

### 6.1 项目集

```text
catalog.json
<项目 ID>/
├─ 项目文件与子目录
└─ .Tiance/
   ├─ state.json
   ├─ conversations/
   └─ 其他项目状态
```

项目集的 `catalog.json` 保存分类、排序、项目身份等索引。同步时会去掉只对当前电脑有效的绝对 `root_path`，并按项目 ID 组织远端目录。另一台设备拉取后，由天策恢复本地项目目录关系。

外部项目同样可以进入项目集同步。提交前应特别检查差异清单，因为项目内容和 `.Tiance` 会话可能包含个人资料、公司文件或模型输出。

### 6.2 知识集与经验集

当前二者使用项目化骨架：

```text
catalog.json
<项目 ID>/
├─ 资料或经验文件
└─ .Tiance/
```

它们分别绑定独立集合类型，不能因为结构相似就与项目集共用同一远端目录。

### 6.3 角色集

```text
catalog.json
<角色项目 ID>/
├─ profile.json
├─ model.json
├─ generation.json
├─ prompt.json
├─ response.json
├─ context.json
├─ memory.json
├─ tools.json
├─ manifest.json          # 来自市场的角色通常包含
└─ .Tiance/
```

集合同步保留角色的本地分类、排序、会话和全部配置。它与角色市场包不同：市场包只允许 `manifest.json` 加八份正式角色配置，共九个文件，不携带本地 `.Tiance` 状态。

### 6.4 主题集

```text
catalog.json
theme-settings.json
<主题 ID>/
├─ theme.json
├─ manifest.json
├─ preview.webp           # 扩展名可使用允许的图片格式
├─ assets/
└─ .Tiance/
```

`theme-settings.json` 保存当前主题选择等本地设置。集合同步会保留整个主题目录；主题市场包则要求至少包含 `theme.json`、`manifest.json` 和合法预览图，背景图片放在 `assets/`。

### 6.5 工具集

```text
catalog.json
<工具项目 ID>/
├─ manifest.json
├─ .tool/
│  ├─ tool.json
│  ├─ input.schema.json
│  ├─ output.schema.json
│  └─ examples.json
├─ program/
│  ├─ main.py             # Python 工具示例
│  ├─ requirements.txt    # 按需
│  └─ config.json         # 按具体工具决定是否存在
└─ .Tiance/
```

工具同步以完整本地工具目录为准。普通工具的 `program/config.json` 可能包含用户自行填写的 Token 或地址，天策不替上传者判断其隐私边界；执行提交前必须检查差异。唯一固定排除的是“GitHub 仓库同步工具”自身的 Token 配置，避免同步凭据形成自我泄漏。

工具市场包至少需要 `manifest.json`、`.tool/tool.json`、输入结构、输出结构和示例文件；Python 工具还必须有有效运行入口。市场包不能包含 `.Tiance`、依赖缓存、Git 仓库或 Python 缓存。

### 6.6 供应商集

```text
catalog.json
<供应商 ID>/
├─ provider.json
├─ credentials.json
├─ models.json
├─ cloud-model-cache.json
├─ provider-rules.json
├─ model-rules.json
├─ manifest.json          # 市场安装项通常包含
└─ .Tiance/
```

集合同步保存完整本地供应商目录，因此可能包含加密凭据、本地模型和缓存。加密不等于可以随意公开，供应商集应当只绑定受控的私人仓库。

供应商在线市场严格不同：公开或私人市场包只能包含以下五个文件：

```text
manifest.json
provider.json
provider-rules.json
model-rules.json
models.json
```

市场包不得包含 `credentials.json` 和 `cloud-model-cache.json`。市场流通的是供应商定义、模型目录和适配规则，不是用户密钥。

## 7. 在线市场仓库结构

所有在线市场的读取入口统一为：

```text
index.json
```

每个可下载项目内部统一使用：

```text
manifest.json
```

但 `manifest.json` 不是整个仓库的索引，也不能代替根目录 `index.json`。推荐源码仓库保留可维护的源目录和构建脚本，由 GitHub Actions 生成 Pages 发布内容：

GitHub 不会自动理解这些文件夹并替天策维护 `index.json`。天策现有公共市场是在源码推送到 `main` 后，由仓库内的 GitHub Actions 运行 `scripts/build_market.py`：脚本校验每个项目的 `manifest.json`，重新生成 `dist/index.json`、安装包和预览资源，再部署到 Pages。正常维护时只需要修改单项文件并推送，不需要手工编辑构建产物；如果私人市场没有配置这套工作流，则必须由仓库维护者自行生成和更新 `index.json`。

```text
.github/workflows/publish.yml
scripts/
schemas/                   # 有正式结构约束的市场可提供
themes/ 或 roles/ 或 tools/ 或 providers/
```

Pages 发布结果通常是：

```text
index.json
packages/
├─ <项目 ID>-<版本>.zip
└─ ...
其他预览资源
```

各类市场包的要求如下：

| 市场 | 单项包核心内容 |
| --- | --- |
| 项目、知识、经验 | 任意有效项目文件夹；`.Tiance/` 是建议结构，不是强制要求；索引可指向压缩包或仓库内目录；普通项目同步仓库也可由 `catalog.json` 自动转换 |
| 角色 | `manifest.json` 与八份角色配置 JSON，共九个正式文件 |
| 主题 | `manifest.json`、`theme.json`、预览图和按需 `assets/` 图片 |
| 工具 | `manifest.json`、标准 `.tool/` 四文件、`program/` 运行实现 |
| 供应商 | 固定五份公开 JSON，不含凭据与本地缓存 |

私人市场通常同样遵守这套 `index.json + 单项 manifest.json` 合同，只是读取方式从公开 Pages 变为经过 GitHub 登录授权的仓库 API。普通项目同步仓库是明确例外：它可以直接使用同步生成的 `catalog.json + <项目 ID>/` 结构，由天策在读取时转换，不要求额外市场文件。

## 8. 备用 Token 方式

GitHub 仓库同步工具还支持在自身 `program/config.json` 中填写 Fine-grained Personal Access Token，作为未登录天策时的备用方式。Token 至少需要目标仓库的 `Contents: Read and write` 权限。

优先推荐天策 GitHub 登录：授权仓库清楚、可以随时从 GitHub 安装设置撤销，并且前端和 AI 工具可以复用同一登录状态。备用 Token 的安全责任由创建和保存它的用户承担，不应提交到在线工具市场或公开仓库。

## 9. 常见问题

### 私人仓库明明已授权，在线市场仍提示无法连接

主题、角色、工具、供应商等市场应先确认仓库根目录内存在有效 `index.json`。普通项目同步仓库可以没有 `index.json`：天策会读取 `catalog.json`；若项目页仍报错，应确认仓库已授权，并至少完成过一次同步提交。

### “检查拉取/检查提交”点击后没有反应

新版界面会显示“正在检查本地与远端差异”。大型项目需要遍历和计算文件版本，耗时会比普通市场刷新更长。如果出现“当前前端与后端版本不一致”，应完整退出并重新启动天策；只刷新前端开发页不能让旧后端获得新接口。

### 项目里打开着 Word 或 PowerPoint 会失败吗

不会。Office 生成的 `~$...` 临时锁文件已被同步快照排除，正式文档仍会正常同步。

### 为什么提交按钮显示只读

检查 GitHub App 的 `Contents` 是否为 `Read and write`，并确认已有安装已经接受更新后的权限。然后回到天策 GitHub 登录页面刷新。

### 多台设备同时修改怎么办

不要直接执行第二台设备上的旧计划。先检查拉取、处理远端变化，再重新检查提交。天策不会静默强推覆盖远端，但它也不是自动合并编辑冲突的 Git 客户端。

## 10. 隐私与责任边界

私人仓库降低了公开泄漏风险，但不等于没有风险。项目文件、`.Tiance` 会话、长期记忆、工具配置和供应商配置都可能包含敏感内容。天策在执行前提供差异预览，并对 GitHub 同步工具自身凭据做固定排除；除此之外，是否上传某个业务文件由仓库所有者判断。

建议：

- 每一集使用独立私人仓库，授权范围只选必要仓库。
- 第一次提交前认真检查新增文件列表。
- 不把私人同步仓库改成公开仓库，除非已经人工审查全部历史提交。
- 发现凭据进入 Git 历史后，不要只删除最新文件；应撤销并重建凭据，同时清理仓库历史。

## 11. 正式代码仓库与旧私人仓库

天策今后的正式开发仓库是：

```text
https://github.com/LikeMirage/Tiance
```

旧的私人开发仓库不再作为代码更新目标，不会自动收到后续源码提交。私人集合仓库只负责用户数据同步，市场仓库只负责内容发布；它们都不等于天策主程序的开发仓库。

如果本地工作区曾经从旧私人仓库拉取，应先检查 `git remote -v`。正式开发工作区的 `origin` 应当指向上面的公开仓库。切换远端只改变代码提交目标，不会自动迁移或删除 `Data/` 中的本地数据。
