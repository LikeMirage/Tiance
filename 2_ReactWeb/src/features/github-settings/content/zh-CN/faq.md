# 常见问题

## 已登录，但看不到仓库

确认 Tiance Desktop 已安装到仓库所属的个人账号或组织。然后打开 GitHub 的 `Installed GitHub Apps → Tiance Desktop → Configure`，选择 `All repositories`，或把目标仓库加入 `Only select repositories`，保存后回到天策刷新。

## 仓库为什么显示“只读”

你的账号、GitHub App 功能权限或仓库授权范围中至少有一层不允许写入。检查 App 是否具备 `Contents: Read and write` 等所需权限，并确认已有安装已经接受新增权限。

## GitHub 显示 `Request`

这通常表示组织要求管理员审批 App。可以等待组织所有者批准，或者先安装到自己的个人账号测试。

## 新建仓库后为什么没有出现

- 使用 `All repositories`：回到天策刷新。
- 使用 `Only select repositories`：进入 App 安装设置，手动加入新仓库后再刷新。

## 没有任何仓库，可以先登录吗

可以。新手建议安装 App 时选择 `All repositories`，完成登录后再让 AI 创建第一个仓库。

## 退出登录等于卸载 App 吗

不等于。退出只清除当前电脑保存的登录凭据。要彻底取消访问，需要在 GitHub 的 `Installed GitHub Apps` 中暂停或卸载 Tiance Desktop；仓库文件本身不会因此删除。

## 需要把密码或 Token 发给 AI 吗

不需要。优先使用天策统一 GitHub 登录。不要在会话、项目文件或公开仓库中发送 GitHub 密码、访问令牌或其他密钥。

## 登录页面一直没有完成

先确认浏览器中的 GitHub 授权已经完成，再检查 `github.com` 和 `api.github.com` 是否可连接。网络中断后验证码可能已经过期，点击取消，然后在网络恢复后重新登录。

## 多台电脑同时修改怎么办

提交前先检查拉取，确认远端没有未同步变化；拉取并处理差异后，再检查提交。不要在两台设备上同时强制覆盖同一仓库。

## 自建 GitHub App 登录失败

检查是否启用了 Device Flow、是否填写了正确的 Client ID、App 是否已经安装到目标账号，以及权限变更后是否重新接受授权。Client ID 不是 App ID，也不是 Client Secret。
