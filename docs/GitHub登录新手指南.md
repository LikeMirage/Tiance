# 天策登录 GitHub：新手上手指南

连接 GitHub 后，你可以让天策里的 AI 更方便地协助管理项目：创建仓库、提交和拉取文件、维护分支、处理 Issue 与 PR、查看 Actions，也可以把项目集等本地集合保存到私人仓库，在不同电脑之间同步。

这些操作不要求另外安装 GitHub Desktop 或 GitHub CLI。普通用户也不需要把 GitHub 密码、Token 或密钥交给 AI；登录和授权在 GitHub 官方页面完成。

本文默认你已经注册并登录 GitHub。GitHub 账号本身的注册和登录不在这里展开。

## 开始前先说清楚：安装 App，不是自己创建 App

普通用户使用天策公开版时，应该安装已经创建好的 **Tiance Desktop GitHub App**，不需要自己再创建一只同名 App。

- **安装 App**：把现成的 Tiance Desktop 接入你的 GitHub 账号，并选择它可以访问哪些仓库。这是普通用户要做的事。
- **登录天策**：让当前电脑上的天策取得你的授权身份。这也是普通用户要做的事。
- **创建 App**：为自己维护的定制版天策注册另一只 GitHub App，并把新 Client ID 写入后端配置。只有开发者或自建版本维护者才需要，步骤放在本文最后。

天策公开版已经内置官方 App 的 Client ID。自己在 GitHub 创建一只新 App，却不修改天策配置，软件仍然会连接官方 Tiance Desktop，而不会使用你新建的 App。

## 一、安装 Tiance Desktop

打开 [Tiance Desktop 安装页面](https://github.com/apps/tiance-desktop/installations/new)。如果 GitHub 要求登录，先完成登录，再继续安装。

### 1. 选择安装到哪个账号

GitHub 会列出可以安装 App 的位置：

- 选择你的个人账号：用于个人仓库，最适合第一次使用。
- 选择某个组织：用于组织仓库。组织可能要求管理员批准；普通成员不一定能直接完成安装。

### 2. 选择仓库范围

GitHub 会显示两个选项：

| 选项 | 实际效果 | 适合谁 |
| --- | --- | --- |
| `All repositories` | 允许 Tiance Desktop 访问该账号当前和以后创建的全部仓库 | 希望 AI 方便管理个人项目的新手 |
| `Only select repositories` | 只允许访问你手动勾选的仓库 | 账号里有敏感仓库，或只想开放少数项目的人 |

**新手推荐选择 `All repositories`。** 这样以后新建仓库不需要反复回到 GitHub 补授权，AI 创建、提交和同步项目也更顺畅。

如果你的账号同时保存公司代码、私人资料或其他不希望天策访问的内容，应改选 `Only select repositories`，只勾选准备用于天策的仓库。

两点容易混淆：

- 选择 `All repositories` 后，该账号以后新建的仓库也会自动进入授权范围。
- 选择 `Only select repositories` 后，由 Tiance Desktop 自己创建的仓库仍会自动获得授权；但你在 GitHub 网页上手动创建的普通仓库不会自动加入，需要稍后手动勾选。

### 3. 检查权限并安装

安装页面会列出 Tiance Desktop 申请的能力。完整的天策 GitHub 工具会使用以下仓库权限：

| 权限 | 用途 |
| --- | --- |
| Metadata：Read | 识别仓库和基础信息，GitHub 自动提供 |
| Contents：Read and write | 读取、提交文件，管理分支、标签、Release 等 |
| Administration：Read and write | 创建、修改、Fork 或删除仓库 |
| Pull requests：Read and write | 创建、审查和合并 PR |
| Issues：Read and write | 管理 Issue、评论、标签和负责人 |
| Actions：Read and write | 查看、触发、重跑、取消工作流运行 |
| Workflows：Read and write | 修改工作流文件 |

确认后点击页面底部的 `Install`。如果安装到组织，按钮也可能显示 `Request` 或 `Install and request`，表示还需要组织管理员批准。

## 二、在天策里登录 GitHub

安装完成后，回到天策：

1. 点击左侧的 **设定集**。
2. 打开 **GitHub 登录**。
3. 点击 **登录 GitHub**。
4. 天策会显示一组设备验证码，并打开 GitHub 官方验证页面。
5. 如果验证码没有自动填入，就把天策显示的验证码输入网页。
6. 在 GitHub 页面确认授权。
7. 回到天策等待页面自动更新。

成功后，页面会显示你的 GitHub 头像、账号名、GitHub App 能力和已授权仓库。

如果页面没有立刻出现仓库，点击 **刷新**。刷新只重新读取授权状态，不会提交、删除或拉取任何文件。

## 三、怎样确认已经配置成功

在“设定集 → GitHub 登录”检查三处：

1. 顶部显示 **已连接**，账号名是你刚才登录的 GitHub 账号。
2. **GitHub App 能力**显示所需权限齐全。
3. **已授权仓库**中能看到目标仓库，并标记为 **读写**。

满足这三项后，天策的 GitHub 工具和仓库同步功能就可以复用这次登录。AI 不需要再次索要 GitHub 密码或 Token。

接下来可以在会话中让 AI：

- 为当前项目初始化 Git 仓库并连接远端；
- 创建 GitHub 仓库并提交项目；
- 查看变化、提交、推送或拉取；
- 创建分支、PR、Issue 和 Release；
- 在各集的在线看板中绑定私人仓库进行同步。

涉及覆盖、删除、合并或强制推送时，仍应先查看 AI 给出的变化说明，再确认执行。

## 四、三层权限到底有什么区别

天策最终能做什么，由三层范围共同决定，不是“登录成功就能操作账号里的一切”。

| 层次 | 直白解释 | 例子 |
| --- | --- | --- |
| GitHub 账号权限 | 你本人对仓库能做什么 | 你对自己的仓库可写，对别人的公开仓库通常只能读 |
| GitHub App 功能权限 | Tiance Desktop 被允许做哪类操作 | 有 Contents 写权限才能提交文件，有 Issues 写权限才能创建 Issue |
| App 的仓库授权范围 | 这只 App 可以进入哪些仓库 | `All repositories` 是全部；`Only select repositories` 是勾选的仓库 |

实际能力取三层的共同部分。例如：

- 你有某仓库写权限，App 也有 Contents 写权限，但该仓库没有被选中：天策不能写。
- 仓库已经选中，App 也有写权限，但你本人只有只读权限：天策仍然只能读。
- 三层都允许写入：天策才可以提交和同步。

这也是为什么“登录”“App 权限”和“选择仓库”是三件不同的事。

## 五、以后怎样添加或移除仓库

在天策打开“设定集 → GitHub 登录”，点击 **添加或移除仓库**。浏览器会进入 GitHub 的 App 安装管理页。

也可以在 GitHub 网页手动进入：

1. 点击右上角头像。
2. 点击 `Settings`。
3. 在左侧 `Integrations` 下点击 `Applications`。
4. 打开 `Installed GitHub Apps`。
5. 找到 `Tiance Desktop`，点击 `Configure`。
6. 在 `Repository access` 中选择 `All repositories`，或在 `Only select repositories` 下增删仓库。
7. 点击 `Save`。
8. 回到天策点击 **刷新**。

这里只改变允许天策访问的仓库，不会删除仓库，也不会改动仓库文件。

## 六、常见问题

### 已登录，但列表里没有仓库

先确认 Tiance Desktop 已经安装到仓库所属的个人账号或组织。然后进入安装配置页，选择 `All repositories`，或把目标仓库加入 `Only select repositories`，保存后回天策刷新。

### 仓库显示“只读”

检查 GitHub 安装页面是否已经接受 Tiance Desktop 的新权限。如果 App 权限刚刚升级，旧安装可能需要重新确认。完成后回天策刷新；页面仍提示缺少能力时，按提示点击 **重新授权**。

### GitHub 显示 `Request`，不能直接安装

这通常表示你正在给组织安装 App，但组织要求管理员批准。可以等待组织所有者批准，或者先把 App 安装到自己的个人账号测试。

### 新建仓库后，天策为什么看不到

- 使用 `All repositories`：回天策刷新即可。
- 使用 `Only select repositories`：如果仓库不是由 Tiance Desktop 创建的，需要在安装配置页手动加入。

### 退出天策登录等于卸载 App 吗

不等于。天策的 **退出登录**只清除当前电脑保存的登录凭据；GitHub 里的 App 安装和仓库选择仍然保留。

要彻底取消访问，需要在 GitHub 的 `Installed GitHub Apps → Tiance Desktop → Configure` 页面选择 `Suspend` 或 `Uninstall`。如果还要撤销 App 代表你操作的登录授权，可在 `Authorized GitHub Apps` 中一并撤销。

### 需要把 GitHub 密码或 Token 发给 AI 吗

不需要。优先使用本指南的软件统一登录。不要把 GitHub 密码、访问 Token 或其他密钥放进会话、项目文件或公开仓库。

## 七、给定制版维护者：创建自己的 GitHub App

本节不是普通用户的必做步骤。只有你维护自己的天策分支，并准备替换公开版内置的 GitHub App 时才需要。

### 1. 在 GitHub 创建 App

1. 点击 GitHub 右上角头像，进入 `Settings`。
2. 左侧最下方进入 `Developer settings`。
3. 点击 `GitHub Apps`。
4. 点击 `New GitHub App`。
5. `GitHub App name` 填写一个全站唯一名称，例如 `Tiance Desktop-你的用户名`。
6. `Homepage URL` 填你的天策仓库地址或 GitHub 个人主页。
7. `Callback URL` 可以留空；天策使用设备登录，不使用网页回调。
8. 保留用户访问令牌过期设置，并勾选 `Enable Device Flow`。
9. 天策不使用 Webhook，取消 `Active`。
10. 在 `Repository permissions` 中按本文前面的权限表设置。
11. `Where can this GitHub App be installed?` 个人自用选择 `Only on this account`；准备让别人安装才选择 `Any account`。
12. 点击 `Create GitHub App`。

### 2. 把新 App 接入自己的天策版本

创建后，在 App 设置页复制 **Client ID**。注意 Client ID 不是 App ID，也不是 Client Secret。

在自己的天策工作区创建或修改：

```text
1_PythonServer/.env
```

写入：

```text
GITHUB_CLIENT_ID=你的Client ID
```

保存并重启天策后，设备登录才会使用你的 App。不要生成或填写 Client Secret；当前设备登录不需要它，也不要把任何 Secret 提交到仓库。

最后回到这只 App 的设置页，点击左侧 `Install App`，选择账号和仓库范围并完成安装。

## 参考

- [安装第三方 GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party)
- [查看和修改已安装的 GitHub App](https://docs.github.com/en/apps/using-github-apps/reviewing-and-modifying-installed-github-apps)
- [GitHub App 用户访问令牌与权限交集](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [注册自己的 GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)

需要了解市场仓库、集合同步和标准 Git 的区别，再阅读[《GitHub 私人仓库连接与同步》](GitHub私人仓库连接与同步.md)。
