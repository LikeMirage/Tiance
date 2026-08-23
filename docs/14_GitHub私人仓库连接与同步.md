# 天策连接 GitHub 私人仓库：授权、市场与多地同步

第一次连接 GitHub，请先阅读[《天策登录 GitHub：新手上手指南》](13_GitHub登录新手指南.md)。本文面向已经完成登录、需要继续了解仓库结构和同步边界的用户。

本文记录天策当前已经实现的 GitHub 私人仓库方案，也解释最容易混淆的三种用法：把私人仓库作为“在线市场”、把本地某一集完整同步到私人仓库，以及把当前普通项目作为标准 Git 仓库维护。

天策不要求用户安装 Git、GitHub Desktop 或其他命令行软件。市场与集合同步使用 GitHub API；普通项目使用软件内置的标准 Git 引擎并生成真实 `.git`。这些路径复用同一份 GitHub 登录。集合看板仍采用可确认的差异计划；AI 工具则用统一的 `dry_run=true` 参数模拟同一操作，不保存临时计划号。

## 1. 先分清三种仓库用途

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

项目集已经把这两种用途明确拆成两种界面模式：选择默认源时显示公共在线市场；选择并绑定 GitHub 私人仓库后，原位置切换为“分类—项目—变化文件”三栏同步看板。私人项目仓库直接使用 `catalog.json + <项目 ID>/`，不冒充市场，也不要求 `index.json` 或 `manifest.json`。其他集合暂未复刻这套私人同步看板，其在线市场仍按正式市场合同读取。

### 1.3 普通项目的标准 Git 仓库

标准 Git 用于维护“当前这个项目”的代码或文档历史。它不需要 `catalog.json`、市场 `index.json` 或集级绑定文件，远端与分支关系直接保存在项目自己的 `.git/config` 中。

内置“Git 仓库”工具支持：

- 查看仓库状态、文件差异、提交历史和指定提交；
- 初始化真实 `.git`，连接或移除 GitHub 远端；
- 创建、切换分支和获取远端状态；
- 通过同一操作的 `dry_run=true` 模拟提交、推送、拉取、恢复、撤销和重置；
- 管理分支、标签和子模块，包括显式的强制推送。

这套能力适合“在当前项目里让 AI 修改自己，然后提交到指定仓库”。如果项目还没有 `.git`，用户只需给出已经创建好的 GitHub 仓库地址，AI 可以依次初始化、连接、检查提交并推送。仓库一旦建立，其他 Git 客户端也能直接使用，不会形成天策专属格式。

标准 Git 工具目前只操作普通项目。角色集、主题集、工具集、供应商集等仍应使用集合同步，因为那些操作需要理解分类、多个项目和本地集合索引，不能由单项目 Git 操作替代。

## 2. GitHub App 从一开始就应当设置为可读写

天策的私人仓库目标是备份、多地同步和由 AI 协助提交，仅有读取权限不能完成这些工作。因此创建或修改 GitHub App 时，仓库权限应当直接设置为：

```text
Repository permissions
└─ Contents: Read and write
```

`Metadata` 的只读权限由 GitHub 自动提供。完整 GitHub 工具套件还需要 `Administration`、`Pull requests`、`Issues`、`Actions` 和 `Workflows` 的读写权限；各权限只用于对应工具。只使用集合私人同步时，`Contents: Read and write` 已足够。

修改 GitHub App 权限后，还要回到该 App 的安装页面确认新的权限。只在 App 设置页把 `Contents` 改成可读写，并不一定会让已有安装立刻获得写权限。

希望让 AI 便捷管理个人账号中各类项目的新手，推荐安装时选择 `All repositories`，以后新建仓库不必反复补授权。账号中存在不希望天策访问的敏感仓库时，再选择 `Only select repositories`，只开放专门用于天策的仓库。需要调整范围时，可从天策“设定集 → GitHub 登录 → 添加或移除仓库”进入 GitHub 安装管理页。

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

项目集还可以直接在“在线项目”的源选择器中选择已授权仓库。选择后会同时保存项目集同步绑定，并把该页面切换到私人同步模式；选择“默认源”会回到公共项目市场，但不会删除已保存的 GitHub 授权。

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

项目集私人同步看板可以按分类、项目或单个变化文件缩小范围。选择分类等于选择该分类下全部项目；选择项目等于选择该项目下全部变化文件。按钮先生成所选范围的差异预览，只有再次确认才会真正拉取或提交。同步所选项目时，`catalog.json` 只合并这些项目的索引信息，不会删除未选项目。

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

### 5.5 2026-08-13：SQLite 工作区的同步注意事项

早期章节和下方目录示例展示的是多份 JSON/JSONL 状态文件。当前项目运行状态已经收口到 `.Tiance/tiance.db`；会话附件仍位于 `.Tiance/conversations/sessions/{session_id}/attachments/`。旧目录图用于说明项目与工作区的归属关系，不再代表当前逐文件存储格式。

`tiance.db-wal` 和 `tiance.db-shm` 是 SQLite 运行时临时文件，不应被当作独立数据文件挑选、编辑或单独恢复。需要完整同步或备份项目时，应先结束该项目的后台会话写入，最好关闭天策后再生成一致快照；恢复时以 `tiance.db` 和附件目录作为一个整体。不要在软件运行过程中只复制数据库主文件，否则可能漏掉尚在 WAL 中的已提交变化。

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

`theme-settings.json` 保存当前主题选择等本地设置。集合同步会保留整个主题目录；主题市场包则要求至少包含 `theme.json`、`manifest.json` 和合法预览图，背景图片放在 `assets/`。市场更新只替换主题定义、主题图片和 `assets/` 资源；`.Tiance/`、本地分类、项目名称及其他非主题文件会迁回新版目录。旧主题目录只作为更新过程中的临时回滚快照，成功后立即清理，不进入回收目录。

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
| 项目、知识、经验 | 任意有效项目文件夹；`.Tiance/` 是建议结构，不是强制要求；公共市场索引可指向压缩包或仓库内目录 |
| 角色 | `manifest.json` 与八份角色配置 JSON，共九个正式文件 |
| 主题 | `manifest.json`、`theme.json`、预览图和按需 `assets/` 图片 |
| 工具 | `manifest.json`、标准 `.tool/` 四文件、`program/` 运行实现 |
| 供应商 | 固定五份公开 JSON，不含凭据与本地缓存 |

私人市场通常同样遵守这套 `index.json + 单项 manifest.json` 合同，只是读取方式从公开 Pages 变为经过 GitHub 登录授权的仓库 API。项目集的私人同步仓库不属于市场：它使用 `catalog.json + <项目 ID>/`，并由独立三栏同步看板操作。

## 8. 备用 Token 方式

GitHub 仓库同步工具还支持在自身 `program/config.json` 中填写 Fine-grained Personal Access Token，作为未登录天策时的备用方式。Token 至少需要目标仓库的 `Contents: Read and write` 权限。

“Git 仓库”工具也支持相同的备用配置，但 Token 只会由工具进程交给后端完成本次授权操作，不会出现在工具输出、提交记录或 `.git/config` 中。标准仓库远端始终保存无凭据的 HTTPS 地址。

优先推荐天策 GitHub 登录：授权仓库清楚、可以随时从 GitHub 安装设置撤销，并且前端和 AI 工具可以复用同一登录状态。备用 Token 的安全责任由创建和保存它的用户承担，不应提交到在线工具市场或公开仓库。

## 9. 常见问题

### 私人仓库明明已授权，在线市场仍提示无法连接

主题、角色、工具、供应商等市场应先确认仓库根目录内存在有效 `index.json`。项目集选择私人仓库后会进入同步看板，不再走市场连接流程；若无法读取，应确认仓库已授权、绑定分支正确，并检查仓库内是否已经存在 `catalog.json`，空仓库则应先从本地检查并提交。

### “检查拉取/检查提交”点击后没有反应

新版界面会显示“正在检查本地与远端差异”。大型项目需要遍历和计算文件版本，耗时会比普通市场刷新更长。如果出现“当前前端与后端版本不一致”，应完整退出并重新启动天策；只刷新前端开发页不能让旧后端获得新接口。

### 项目里打开着 Word 或 PowerPoint 会失败吗

不会。Office 生成的 `~$...` 临时锁文件已被同步快照排除，正式文档仍会正常同步。

### 为什么提交按钮显示只读

检查 GitHub App 的 `Contents` 是否为 `Read and write`，并确认已有安装已经接受更新后的权限。然后回到天策 GitHub 登录页面刷新。

### 多台设备同时修改怎么办

不要直接执行第二台设备上的旧计划。先检查拉取、处理远端变化，再重新检查提交。天策不会静默强推覆盖远端，但它也不是自动合并编辑冲突的 Git 客户端。

### 集合同步和“Git 仓库”工具该选哪个

要同步整个项目集、主题集或工具集，使用在线看板里的集合同步；要维护当前一个普通项目的版本历史，使用“Git 仓库”工具。前者理解 `catalog.json` 和多项目选择，后者理解标准 `.git`、提交和分支。两者共享 GitHub 登录，但不会共享或覆盖彼此的绑定状态。

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
