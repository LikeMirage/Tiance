# 04 能力桥、现有接口与扩展边界

## 选择执行方式

文件处理、独立网络 API、转换和计算优先 Python 工具。需要前端产品操作及界面状态时使用已登记的 client 能力。需要模型集密钥、GitHub 登录或由宿主管理的数据时，通过受限的宿主能力桥。桥与接口只负责开放明确能力，不应成为执行任意前端 JavaScript 或任意后端函数的入口。

## 前端能力桥

工具清单示例（片段，须保留其余标准字段）：

```json
{
  "runtime": {
    "type": "client",
    "timeout_seconds": 180,
    "client_capability": {"name": "tool.projects", "min_version": 1}
  },
  "io": {"input": "client_json", "output": "client_json"}
}
```

平台按能力名称和版本分发，不按某个具体工具名分支。清单里随便写一个能力名称不会产生实现；前端必须实际登记。一个能力可以被不同调用名的工具复用。新增 client 工具的 Python 入口不会自动被执行，实际程序是已登记的前端执行器。

调用过程：模型 tool call → 后端校验参数、权限、启用与能力兼容 → 创建 client 请求 → 前端领取请求 → 执行已有产品 API/界面操作 → 提交标准结果 → 后端继续工具循环。

请求上下文包括 request_id、call_id、name、arguments、调用方 project_id/session_id、timeout_seconds、model_context、client_capability，以及 tool_project_id。最后一项是后端从注册表确定的“被调用工具项目”，不能由模型参数伪造，也不能与调用方项目混用。动态工具执行时它指向实际目标工具。

前端执行器接收 `{signal}`，应响应取消。跨窗口只有租约持有者执行；已完成结果可以重提，执行状态未知的重放不会自动重复副作用。不要跳过 `clientToolRequestSingleFlight.ts` 直接执行流事件。不要回退到“当前界面恰好打开的项目”，切换页面不应该改变工具的目标。

### 当前可查的前端能力

| 能力 | 版本 | 作用与源码 |
| --- | --- | --- |
| `editor.tabs` | 1 | 编辑器标签，查看 editorTabsClientTool.ts、backgroundEditorTabsClientTool.ts |
| `conversation.management` | 1 | 会话列表、读取、创建、配置等，conversationManagementClientTool.ts |
| `conversation.interaction` | 1 | 向会话发送任务、等待等，conversationInteractionClientTool.ts |
| `tool.projects` | 1 | 分类查询、分类创建、工具模板创建，toolProjectClientTool.ts |

以当前注册表为准，不能从这张表推断其他动作已开放。参数应读取对应工具 input.schema.json 和执行器，不要猜动作名。

### tool.projects v1

- `{"action":"list_categories"}`：返回 category_id、name、readonly。
- `{"action":"create_category","name":"我的工具"}`：调用既有分类创建接口并返回分类。
- `{"action":"create_tool","category_id":"已查询的分类 ID","name":"工具名称","call_name":"optional_call_name"}`：从执行工具自身 `assets/scaffold.json` 读取模板，创建并装配新项目。

索引合同：version=1、template_version 字符串、documentation 为生成后的文档入口路径、files 为 source/target 数组。source 必须是该工具 assets 下的相对路径；target 必须在新项目内且不能覆盖 .Tiance。全部读取与基本检查成功后才创建；五份标准 JSON 和 program/main.py 必须存在。清单的 name/registration_name 用调用参数或新项目身份生成；state.enabled 始终强制 false；其他模板设置保留。最后写清单，避免注册半成品。资料与模板属于工具项目，更新它们不需要把正文写进前端源码。

使用了现有 API：`GET/POST /api/tools/categories`、`POST /api/tools/categories/{category_id}/projects`、项目文件读取及工具文件内容保存。前端复用带当前认证的 httpClient，不把用户登录凭据交给模型或工具包。完成后通过目录事件刷新列表，不强制用户切换正在查看的项目。

### 扩展新的前端能力

1. 先检查现有 services 和注册能力，确认真正缺的是哪种通用产品能力。
2. 在 client-tools/model 实现执行器，提供稳定 capability name/version，复用已有 API。
3. 在统一注册组合处登记，使正常会话与后台会话都收到能力；有版本不兼容时明确升级版本。
4. 对缺少上下文、参数错误、取消、重复派发、页面切换、失败后部分完成写测试。
5. 新工具清单引用该能力。无需在聊天核心中按工具名增加业务分支。

如果现有后端 API 已满足要求，通常只需前端接入；若请求缺少通用上下文或后端尚无对应业务接口，则需同步补合同和后端实现。改源码后更新前端构建，并在合适时机重启应用。client 工具要求前端连接，不能承诺关掉窗口还会继续执行。

## 宿主能力桥：Python 使用受限宿主能力

使用应用提供的帮助函数，而非自己寻找模型 Key：

```python
from tiance_runtime import call_host_capability

# 仅对已获 web_search 授权的工具有效；复制代码不代表获得授权。
result = call_host_capability("web_search", {"query": "待搜索的问题"}, timeout_seconds=30)
```

平台为允许的调用名签发带能力类型、调用方上下文和过期时间的短期凭据，注入 TIANCE_HOST_CAPABILITY_TOKEN，结束后撤销。帮助函数使用 TIANCE_API_BASE_URL 并附带 Bearer 凭据。API 基址不是认证，短期凭据也不能当作浏览器会话凭据访问任意普通接口。

### 当前映射

| 能力 | 相对 API 基址的路径 | 授权调用名 |
| --- | --- | --- |
| web_search | /llm/provider-capabilities/web-search | network_search |
| deepseek_web | /llm/provider-capabilities/deepseek-web | deepseek_official_web_search |
| github_sync | /github/sync/tool | github_repository_sync |
| git_repository | /git/repository/tool | git_repository |
| github_platform | /github/platform/tool | github_repository、github_pull_request、github_issue、github_release、github_actions |
| memory_management | /memory/management/tool | manage_memory |

宿主桥当前确实使用后端白名单绑定调用名，与前端桥按 capability 匹配不同。修改这些工具调用名可能使授权消失。没有项目创建的宿主授权，不能用此桥凭据直接调用工具分类创建接口。

### 扩展宿主能力需要哪些源码

1. `services/tools/host_capability_access.py`：能力枚举、调用名允许策略与凭据范围。
2. `tiance_runtime.py`：能力名称到端点的映射（新增能力时）。
3. `api/routes/` 与 `schemas/`：请求合同、Bearer 授权校验、路由挂载；宿主业务应调用现有服务，不复制逻辑。
4. 网关/认证层：核对受限能力端点的实际放行方式；不能把整个普通 API 前缀加入匿名白名单。检索该端点及 HOST_CAPABILITY 在网关源码中的使用。
5. 测试：未授权、过期、错误能力、取消、范围越界、凭据不泄露，以及实际模型/凭据解析。

若只是允许另一工具使用已经存在的能力，也需审查并修改允许策略，不能把任意工具全部开放。协议和供应商差异应留在宿主适配层，普通工具不直接读取供应商配置、主后端数据库或进程内服务单例。

## 普通 HTTP 接口和桌面壳

浏览器 API 走现有 httpClient，遵守访问密码和认证；Python 工具默认没有浏览器 Cookie，本机 127.0.0.1 不代表免授权。确实需要宿主能力时按上文扩展，不能通过关安全设置解决。

桌面壳 API 是另一个边界，见 `3_PyWebView/app/api.py` 及前端 desktop 服务的实际定义；不是写个 client 能力名就能调用任意本机动作。桌面、浏览器和远程访问的能力可能不同，需要明确判断，不假定远程前端的电脑就是后端所在电脑。
