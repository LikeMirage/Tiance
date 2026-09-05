# 在线市场与 GitHub

## 市场模型

项目、知识、经验、角色、主题、工具和供应商拥有各自市场路由与包合同，共享在线市场网关、来源设置、缓存和 GitHub 私库读取能力。

远端通常包含：

- `index.json`：市场索引；
- `manifest.json`：稳定 ID、版本、兼容性和完整性；
- ZIP 或项目文件；
- 可选预览资源。

本地分类、排序、密钥、运行状态和用户设置不由远端索引决定。缓存只用于展示已校验索引，不能代替安装时重新校验。

## 安装与更新

安装流程应使用 staging 目录，验证包大小、SHA-256、Schema、稳定 ID、版本和路径后再替换。市场项目更新必须保护本地所有权：不同类型允许替换的文件不同，不能用递归字段名匹配修改项目内所有 JSON。

并发安装或更新同一项目需要项目级互斥和事务边界。更新工具时还需协调正在运行的工具和依赖任务。

## 远端安全

- 默认只接受 HTTPS 和规范 GitHub 仓库地址。
- 相对包路径必须留在当前市场/仓库。
- DNS 解析结果、重定向后的最终地址和实际连接目标都要阻止回环、私网和保留地址。
- 仅在请求发出后检查最终 URL 不能阻止重定向 SSRF。
- 下载预算应覆盖索引、文件数、总字节和解压后大小。

## GitHub 登录

当前通过 GitHub 设备流程登录，并读取 GitHub App 安装范围。凭据保存在本地 secrets 存储中并受系统秘密保护；市场设置和普通项目文件不得保存 Token。

用户必须在 GitHub App 安装页面授权具体仓库。需要推送、创建 Release、PR、Issue 或运行 Actions 时，还需对应 GitHub 权限；前端显示状态不能绕过 GitHub 的真实授权。

## 三类 GitHub 能力

| 能力 | 作用范围 |
| --- | --- |
| 普通项目 Git | 当前项目的 `.git`、提交、分支、远端、推拉 |
| GitHub 平台工具 | Release、PR、Issue、Actions 等平台对象 |
| 集合同步 | 项目集/角色/主题/工具等集合的选择性镜像与绑定 |

三者可以共享登录，但绑定状态、业务合同和正式事实不同，不能互相替代。

## 供应商包

供应商市场包可发布公开定义、模型模板与声明规则，不得包含凭据。已有供应商更新应限制在明确允许的公开文件；改变数据结构、Profile 身份或需要新程序能力时，应提高最低天策版本或使用新的稳定 ID。

## 实现索引

- 在线市场网关：`1_PythonServer/app/services/application/online_market.py`
- 远端客户端：`1_PythonServer/app/infra/online_market/remote_client.py`
- 地址安全：`1_PythonServer/app/infra/online_market/remote_security.py`
- GitHub 登录：`1_PythonServer/app/services/application/github_connection.py`
- 集合同步：`1_PythonServer/app/services/application/github_sync.py`
- Git 工具路由：`1_PythonServer/app/api/routes/git_repository.py`
- GitHub 工具路由：`1_PythonServer/app/api/routes/github_platform.py`
