# Git 与 GitHub 工具：能力、授权和操作说明

天策把“本地版本历史”和“GitHub 平台管理”分成六个扁平工具。它们共享软件内的 GitHub 登录，但职责互不混合：本地 Git 工具只操作当前会话所属普通项目；五个 GitHub 工具只调用 GitHub 官方接口。

普通用户不需要安装 Git、GitHub Desktop 或 GitHub CLI。天策使用内置 Git 引擎创建真实 `.git`，因此仓库以后仍可交给任何标准 Git 客户端继续维护。

## 1. 六个工具分别做什么

| 工具 | 主要能力 |
| --- | --- |
| Git 仓库 | 当前项目状态、差异、历史、提交、远端、推送、拉取、分支、标签、子模块、恢复、撤销和重置 |
| GitHub 仓库 | 列出、查看、创建、修改、Fork 和删除远端仓库 |
| GitHub PR | 比较分支、创建/编辑 PR、评论、审查、更新分支和合并 |
| GitHub 议题 | Issue、评论、标签和负责人 |
| GitHub 发布 | Release 的创建、编辑、删除及附件上传/删除 |
| GitHub Actions | 工作流、运行、任务、日志、手动触发、重跑、取消和删除运行 |

工具都是工具集中的普通项目，没有“内置工具”特例。它们通过天策的后端能力桥取得当前会话项目和临时 GitHub 身份；AI 不会拿到任意磁盘路径，也不会从一个会话越界操作另一个项目。

## 2. `dry_run` 就是模拟参数

所有会产生修改的工具操作都接受：

```json
{"dry_run": true}
```

它不是权限、审批、锁定或临时计划系统，只是该工具本次调用的模拟参数。返回值说明将执行的动作和相关对象，但不写入本地项目或 GitHub。确认后，用完全相同的参数把 `dry_run` 改为 `false` 或省略即可真正执行。

读取操作（状态、差异、列表、详情和日志）本身不修改内容，不需要模拟。集合私人同步看板仍保留自己的差异确认界面，因为它面向人按分类、项目和文件选择同步范围，与 AI 工具的调用方式不同。

强制推送和硬重置使用显式 `force=true`，不会因普通推送或普通重置而暗中发生。后续统一工具权限系统可以在工具外层控制这些动作；本版没有提前加入另一套权限状态。

## 3. 推荐登录：软件内统一 GitHub 登录

打开“设定集 → GitHub 登录”，完成设备验证码登录并安装 Tiance Desktop GitHub App。登录凭据加密保存在本机 `Data/secrets/github-auth.json`，工具运行时只取得本次请求需要的临时访问令牌，不把令牌写进模型输入或工具返回。

GitHub App 建议从一开始配置以下 Repository permissions：

| GitHub App 权限 | 级别 | 用途 |
| --- | --- | --- |
| Metadata | Read | GitHub 自动提供，识别仓库 |
| Contents | Read and write | 读取/提交代码、标签、Release 及附件 |
| Administration | Read and write | 创建、修改、Fork、删除仓库 |
| Pull requests | Read and write | PR、审查和合并 |
| Issues | Read and write | Issue、评论、标签和负责人 |
| Actions | Read and write | 查看、触发、重跑、取消和删除工作流运行 |
| Workflows | Read and write | 修改工作流文件以及完整工作流操作 |

设定页会读取 GitHub 返回的实际安装权限。缺项时会直接列出权限名并显示“重新授权”，而不是等某个工具失败后再猜原因。

### 修改权限后的必要操作

修改 GitHub App 权限不会自动让旧安装接受新增权限。应用所有代码更新后，仓库所有者还需要完成一次人工操作：

1. 打开 GitHub App 的 Developer settings，把上表权限设为对应级别并保存。
2. 打开 GitHub 个人设置中的 Applications → Installed GitHub Apps → Tiance Desktop → Configure。
3. 接受新增权限；选择 `All repositories`，或在 `Only select repositories` 中加入需要操作的仓库。
4. 回到天策“设定集 → GitHub 登录”点击刷新。
5. 确认“GitHub App 能力”显示权限齐全，仓库行显示“读写”。如 GitHub 要求重新授权，则退出登录后重新走一次设备登录。

推荐使用 `Only select repositories`。创建新仓库后如果工具暂时看不到它，需要回到安装配置页把新仓库加入授权范围。

## 4. 备用登录：工具自己的 Token 配置

若无法使用软件登录，每个 GitHub/Git 工具的 `program/config.json` 都可填写：

```json
{"github_token": "你的 Token"}
```

软件登录存在时优先使用软件登录，不读取这里的 Token。该文件是用户自行控制的明文高级配置，不能上传到公开市场、公开仓库或发送给别人。公开工具市场中的配置值始终为空。

Fine-grained personal access token 必须覆盖目标仓库，并拥有与所调用操作相符的权限。传统 PAT 权限范围更宽，不推荐作为默认方式。

## 5. 从空文件夹发布一个项目

如果项目已经在天策项目集中打开，AI 可以按以下流程完成首次发布：

1. `github_repository` 创建远端仓库；可先 `dry_run=true`。
2. `git_repository` 在当前项目执行 `init`。
3. `git_repository` 执行 `connect_remote`，连接刚创建的 HTTPS 地址。
4. `git_repository` 用 `commit + dry_run=true` 查看将提交的文件，再执行真实提交。
5. `git_repository` 用 `push + dry_run=true` 检查，再推送到 `main`。

项目已有 `.git` 时不需要额外绑定。远端地址和分支保存在标准 `.git/config` 中，与手工使用 Git 完全一致。

## 6. 常见完整流程

### 修改代码并提交

1. 读取 `status` 和 `diff`。
2. 修改文件并运行项目验证。
3. `commit` 先模拟，再真实提交。
4. `push` 先模拟，再真实推送。
5. 需要协作审查时，用 GitHub PR 工具创建 PR，而不是直接合并主分支。

### 发布新版本

1. 确认工作区干净、测试和构建通过。
2. 用 Git 工具创建版本标签并推送代码。
3. 用 GitHub 发布工具创建 Release。
4. 上传当前项目内的发布包；附件路径被限制在当前项目根目录，不能借此读取其他磁盘位置。
5. 用 GitHub Actions 工具检查构建运行和任务日志。

### 处理外部贡献

1. 列出 PR，读取详情、文件和审查记录。
2. 必要时评论或提交审查意见。
3. 检查分支状态并更新 PR 分支。
4. `merge + dry_run=true` 预览目标 PR，再选择 merge、squash 或 rebase 合并。

## 7. 当前边界

- Git 工具只操作当前普通项目，不替代主题集、工具集等集合级同步。
- Release 附件只能来自当前项目。
- 拉取采用快进策略；本地与远端分叉时不会悄悄合并。
- 强制推送和硬重置必须显式传 `force=true`。
- 子模块使用标准 `.gitmodules`；私人子模块还取决于其自身仓库授权。
- Git LFS 需要完整的 LFS 对象传输协议，本版没有伪装成已支持。仓库里的 LFS 指针文件可以作为普通文件管理，但不能承诺上传/下载 LFS 大对象。
- GitHub App 能做什么最终由 GitHub App 配置和仓库安装范围共同决定，天策前端不能绕过 GitHub 权限。

## 8. 排查顺序

遇到 404 或“仓库不存在/未授权”时，按顺序检查：

1. 仓库名称和所有者是否正确。
2. Tiance Desktop 是否安装到仓库所属账号或组织。
3. 该仓库是否在 App 的授权范围中。
4. 设定页权限是否齐全。
5. 修改 App 权限后是否接受了新增权限并重新授权。
6. 当前分支、Release ID、PR/Issue 编号或 Actions Run ID 是否真实存在。

这套设计的核心边界是：Git 负责当前项目的真实版本历史，GitHub 工具负责远端平台对象，集合私人同步负责整个数据集的镜像与选择性同步；三者共享登录，但不互相冒充。
