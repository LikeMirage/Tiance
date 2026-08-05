# 源码提交与 GitHub 推送流程

这份文档只说明“把源码和标签推送到 GitHub”。它不负责制作压缩包，也不负责创建 GitHub Release。

## 一、发布前确认

在仓库根目录执行：

```powershell
cd C:\Users\WW\Desktop\Tiance
git status --short
git branch --show-current
git remote -v
```

必须确认当前仓库是 `LikeMirage/Tiance`、分支是 `main`，并且没有把 `Data/`、密钥、会话数据、缓存和个人临时文件加入提交。

先同步远端：

```powershell
git pull --ff-only origin main
```

如果工作区存在不认识的修改，先停下来检查，不要直接使用 `git add -A`。

## 二、构建和验证

前端改动必须重新生成生产文件：

```powershell
cd 2_ReactWeb
pnpm install --frozen-lockfile
pnpm check
pnpm build
cd ..
```

后端或更新器改动，应运行对应测试。发布前至少确认：

```powershell
git diff --check
git status --short
```

## 三、提交源码

只添加本次真正需要发布的文件：

```powershell
git add system/version.json 2_ReactWeb/dist
git add 需要发布的源码文件
git diff --cached --stat
git diff --cached --check
git commit -m "chore: release vX.Y.Z"
git push origin main
```

推送后确认提交已经在远端：

```powershell
git log -1 --oneline origin/main
```

## 四、创建并推送标签

一个正式版本只使用一个不可移动的标签：

```powershell
git tag -a vX.Y.Z -m "Tiance vX.Y.Z"
git push origin vX.Y.Z
```

标签一旦推送，不要再把它指向另一个提交。如果发布包有错误，增加补丁版本重新发布，例如从 `v0.3.11` 改为 `v0.3.12`。

## 五、源码推送和 Release 的区别

`git push` 只完成源码分支和标签同步，不会自动上传压缩包，也不会自动创建 Release。创建 Release 和上传附件必须另行执行，见《发布包与在线更新包制作流程》。

Git 的登录凭据和 GitHub API/CLI 登录凭据是两套独立凭据。源码能够推送，不代表 `gh release create` 一定已经登录。

## 六、标准维护者发布入口

优先使用 GitHub CLI：

```powershell
gh auth login
gh auth status
```

CLI 登录后，使用已推送的标签创建 Release：

```powershell
gh release create vX.Y.Z `
  发布包/Tiance.zip `
  发布包/Tiance-update.zip `
  发布包/update.json `
  --repo LikeMirage/Tiance `
  --verify-tag `
  --title "Tiance vX.Y.Z"
```

也可以在 GitHub 网页的 Releases 页面选择已经推送的标签手工创建。软件内部的 GitHub 登录主要服务于应用内 GitHub 工具，不是维护者发布源码的前置条件。

