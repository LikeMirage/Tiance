# 快速开始

## 0. 先确认网络可以连接 GitHub

登录和仓库操作需要访问 `github.com`、`api.github.com` 和 GitHub 设备验证页面。开始前建议先用浏览器打开 [GitHub](https://github.com/)；如果页面或登录接口无法连接，请检查当前网络、DNS、系统代理、防火墙或所在组织的网络策略，也可以在天策的“网络设置”中配置允许使用的代理后重新测试。

网络尚未连通时不要反复点击登录。设备验证码有效期有限，恢复连接后重新开始即可。

## 1. 安装 Tiance Desktop GitHub App

打开 [Tiance Desktop 安装页面](https://github.com/apps/tiance-desktop/installations/new)。普通用户是**安装现有 App**，不需要自己创建 GitHub App。

如果还没有 GitHub 账号，先在 GitHub 完成注册和登录，再返回安装页面。

## 2. 选择个人账号或组织

- 第一次使用建议安装到自己的个人账号。
- 安装到组织时，GitHub 可能要求组织管理员批准；出现 `Request` 并不表示天策故障。

## 3. 给足仓库范围和功能权限

新手建议选择 **All repositories**。这样当前仓库和以后新建的仓库都能直接使用，不需要每次回到 GitHub 补授权。

如果目前一个仓库都没有，也可以正常安装和登录。稍后可以让天策中的 AI 创建第一个仓库；选择了 **All repositories** 后，新仓库会自动进入授权范围。

安装页面应显示并允许 Tiance Desktop 使用以下仓库能力：

| 权限 | 级别 | 用途 |
| --- | --- | --- |
| Metadata | Read | 识别仓库和基础信息 |
| Contents | Read and write | 读取和提交文件，管理分支、标签与 Release |
| Administration | Read and write | 创建、修改、Fork 或删除仓库 |
| Pull requests | Read and write | 创建、审查和合并 PR |
| Issues | Read and write | 管理 Issue、评论和标签 |
| Actions | Read and write | 查看、触发、重跑或取消工作流 |
| Workflows | Read and write | 修改工作流文件 |

如果 GitHub 要求确认新增权限，请接受后再继续。只给读取权限会导致提交、同步、创建仓库等功能不可用。

老用户如果只想开放少量仓库，可以选择 **Only select repositories** 并自行维护授权范围。

## 4. 返回天策完成设备码登录

1. 切换到本页的“登录”标签。
2. 点击“登录 GitHub”。
3. 浏览器打开 GitHub 官方设备登录页面后，输入天策显示的验证码。
4. 确认授权，然后回到天策等待页面自动更新。

设备验证码不需要发给 AI。登录完成后，天策会在本机安全保存授权信息。

## 5. 检查是否配置成功

回到“登录”标签确认：

1. 显示的 GitHub 账号正确。
2. GitHub App 能力没有缺失提示。
3. 目标仓库出现在已授权仓库中，并显示为“读写”。

没有仓库的新用户只需确认账号和 App 能力正常，然后让 AI 创建第一个仓库即可。

## 自建 GitHub App（定制版维护者）

普通用户无需执行本节。只有维护自己的天策分支并希望使用自己的 GitHub App 时才需要：

1. 在 GitHub `Settings → Developer settings → GitHub Apps` 中创建 App。
2. 勾选 **Enable Device Flow**；天策不使用网页回调，也不需要 Client Secret。
3. Webhook 可以关闭。
4. 按上方权限表设置 Repository permissions，并保存。
5. 将 App 安装到自己的账号，建议新手选择 **All repositories**。
6. 复制 **Client ID**，在源码工作区的 `1_PythonServer/.env` 中设置：

```text
GITHUB_CLIENT_ID=你的Client ID
```

重启天策后，设备登录会使用这只 App。不要把 Client Secret、访问令牌或其他密钥提交到仓库。
