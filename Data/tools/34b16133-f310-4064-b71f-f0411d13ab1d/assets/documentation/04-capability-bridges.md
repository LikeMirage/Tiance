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

普通 Python 工具直接处理文件或调用外部 API，不需要能力桥。需要复用天策的模型凭据、GitHub 登录、记忆管理或工具目录时，声明所需能力，再使用 SDK。工具名称不参与能力授权，复制工具或修改调用名不会丢失已声明的能力；调用名仍须在工具集中唯一。

### 接入一个已有能力

在本工具 `.tool/tool.json` 的 runtime 中声明，保留其他标准字段：

```json
{
  "runtime": {
    "type": "python",
    "entry": "program/main.py",
    "timeout_seconds": 60,
    "host_capabilities": ["tool_catalog"]
  }
}
```

`host_capabilities` 是可选数组，省略或空数组表示不申请宿主权限。只能填当前注册表中的能力名称；未知名称、非数组、非字符串元素都会使配置校验失败。非 Python 执行类型不能声明非空数组。需要多个能力可以列出多个，但应只声明业务实际需要的能力。它不属于模型输入参数，也不替代 input.schema.json 的参数权限。

入口示例（实际工具的输入 Schema 须声明 tool_name）：

```python
from tiance_runtime import call_host_capability, run_tool

def main(arguments):
    detail = call_host_capability(
        "tool_catalog",
        {"operation": "get_parameters", "tool_name": arguments["tool_name"]},
        timeout_seconds=20,
    )
    return {"ok": True, "data": detail}

if __name__ == "__main__":
    run_tool(main)
```

平台先检查工具启用、会话选择、参数与权限，然后从实际目标工具的配置读取声明，签发本次调用的短期凭据。凭据绑定能力集合、工具项目、调用 ID、调用方项目/会话、模型上下文和运行身份；工具运行成功、失败或取消后都会撤销。动态执行时按被执行工具自己的声明授权，不继承外层工具的全部权限。

SDK 从环境读取 `TIANCE_API_BASE_URL` 和 `TIANCE_HOST_CAPABILITY_TOKEN`，发送受限 POST 请求。不要把 token 写进 input.schema、返回给 AI、保存到工具配置或打印日志。手动运行程序不会自动获得授权；不要复制浏览器 Cookie 或全局网关密钥来补齐它。

### 后端能力清单

以下路径相对 `TIANCE_API_BASE_URL`（一般已经含 `/api`）；调用 SDK 时只传能力名称。所有端点均要求对应能力的 Bearer 凭据。

| 能力名称 | POST 路径 | 用途与边界 |
| --- | --- | --- |
| `web_search` | `/llm/provider-capabilities/web-search` | 使用本次调用的供应商/模型执行内置搜索；要求模型上下文 |
| `deepseek_web` | `/llm/provider-capabilities/deepseek-web` | 使用模型集 DeepSeek 凭据调用 Search/Fetch，不把 Key 返回给工具 |
| `github_sync` | `/github/sync/tool` | 调用方项目与 GitHub 仓库的绑定、推送、拉取；复用宿主登录 |
| `git_repository` | `/git/repository/tool` | 调用方项目的本地 Git、远端及分支等操作 |
| `github_repositories` | `/github/platform/repositories` | GitHub 仓库查询、创建及管理 |
| `github_pull_requests` | `/github/platform/pull-requests` | GitHub PR 查询及管理 |
| `github_issues` | `/github/platform/issues` | GitHub Issue 查询及管理 |
| `github_releases` | `/github/platform/releases` | GitHub Release、附件查询及管理 |
| `github_actions` | `/github/platform/actions` | GitHub Actions 工作流、运行及产物操作 |
| `memory_management` | `/memory/management/tool` | 调用方项目记忆与全局记忆管理 |
| `tool_catalog` | `/tools/capabilities/catalog` | 读取本次调用范围内工具的参数和案例 |
| `run_status` | `/tools/capabilities/run-status` | 只读查询所属生成任务，也可申请短期观察租约 |

注册表位于 `1_PythonServer/app/domain/tools/host_capabilities.py`。SDK 提供 `list_host_capabilities()`，本地返回 name/path/description 清单，不发请求、不泄露凭据，也不代表本次调用获准使用清单里的全部能力。注册表同时供清单校验、SDK 和网关读取，避免各自维护不同列表。

### 各类能力的请求方式

下列是能力端点的请求体示例，不能原样当成任意工具的输入 Schema。业务工具可以提供更适合用户的参数，再转换为能力请求；仍须保留真实操作对应的参数权限。

**模型搜索：**

```python
call_host_capability("web_search", {"query": "待搜索的问题"}, timeout_seconds=30)
call_host_capability("deepseek_web", {
    "action": "search", "query": "待搜索的问题", "count": 5, "need_content": False
}, timeout_seconds=30)
call_host_capability("deepseek_web", {"action": "fetch", "url": "https://example.com/"}, timeout_seconds=30)
```

`web_search` 只接收 query，模型身份来自后端授权上下文。DeepSeek Search 的 count 为 1–50；其他选项及返回合同见 `app/schemas/llm/deepseek_web.py` 和对应路由。官方 DeepSeek 工具自己的 config.json Key 优先逻辑属于工具程序：自行配置了 Key 时直接调用官方接口，没配置才复用模型集能力。能力桥本身不替工具修改私有 config.json。

**Git 与 GitHub：**

```python
call_host_capability("git_repository", {"action": "status"}, timeout_seconds=20)
call_host_capability("github_sync", {"action": "overview"}, timeout_seconds=30)
call_host_capability("github_repositories", {"action": "list_repositories"}, timeout_seconds=30)
```

`github_sync` 支持 overview、list_repositories、get_binding、bind、unbind、plan_push、push、plan_pull、pull，参数定义见 `app/schemas/github_sync.py`。本地 Git 操作与字段见 `app/schemas/git_repository.py`；项目目标由调用上下文确定，不通过伪造项目 ID 切换工作区。

五类 GitHub 平台能力使用 `{action, dryRun, parameters}` 合同，参数定义见 `app/schemas/github_platform.py`，各类动作及校验见 `app/services/application/github_platform.py` 的 `_ALLOWED`、`_MUTATIONS` 和校验函数。修改操作支持的预检并不代替真实权限与业务校验。五种能力各有固定资源域，仓库能力不能通过改 action 或工具名变成 Release 能力。认证使用宿主登录；工具自行配置的备用 GitHub Token 仍沿现有 SDK 受控请求头传递，不是模型参数。

**记忆与工具资料：**

```python
call_host_capability("memory_management", {"operation": "list", "scope": "project"}, timeout_seconds=20)
call_host_capability("tool_catalog", {
    "operation": "get_parameters", "tool_name": "read_text_file"
}, timeout_seconds=20)
call_host_capability("tool_catalog", {
    "operation": "get_examples", "tool_name": "read_text_file", "include_all": True
}, timeout_seconds=20)
```

记忆操作有 list、search、add、update、delete；全局/项目范围及字段见 `app/schemas/memory_management.py`。项目记忆以授权里的项目身份为准。

工具参数响应包含 name、input_schema、summary；案例响应包含 name、count、items，可用 indexes 或 titles 选择。目录查询同时校验本次允许工具列表与会话当前设置，不能读取会话禁用的工具。请求体不接受 project_id、session_id 等伪造范围字段。普通 `/api/tools/catalog/...` 是界面接口，Python 工具应走这里的能力端点。

**任务观察与后台助手：**

```python
call_host_capability("run_status", {"action": "status"}, timeout_seconds=5)
# 只有确需在工具返回后观察同一个生成任务的后台助手才使用 watch：
lease = call_host_capability("run_status", {"action": "watch"}, timeout_seconds=5)
```

status 返回 running 和 run_id。身份是运行管理器的实时生成任务 ID，与落盘用量记录中的轮次 ID 不同，不允许由工具参数自行指定。

watch 返回绑定该任务的只读 token 和 lease_seconds（当前 90 秒）。后台助手只接收这枚观察 token，不继承父工具的其他能力；例如 GUI 工具通过子进程环境 `TIANCE_RUN_OBSERVER_TOKEN` 传入。它使用这枚 token 向同一端点 POST `{"action":"status"}`；服务器先检查任务仍是原来那一轮，才续租。父工具返回不影响此观察租约；任务结束、换代或超过租约时间未查询后失效。观察者不能再申请观察租约，也不能读取会话内容、控制任务或访问其他能力。不要把观察 token 放入工具返回值、命令行或磁盘状态文件。

### 授权边界与常见排错

能力声明属于安装工具时信任的配置，天策没有 Python 沙箱；它让宿主接口的权限和目标明确，并不把不可信 Python 程序变成安全程序。它也不会替用户开启工具、跳过参数权限或解除会话工具选择。

- 缺少宿主授权：检查 runtime.host_capabilities、是否经平台执行、是否已加载新配置，以及所需模型上下文是否存在。
- 401 / 授权过期：检查调用是否已经结束、token 是否属于对应能力；不要将本次 token 持久保存供下次使用。
- `GATEWAY_AUTHENTICATION_REQUIRED`：很可能直接调用了普通界面 API，或运行的仍是旧后端；核对 SDK 能力路径和后端版本。
- 未知能力：查 `list_host_capabilities()` 与注册表；写一个名称不会自动生成实现。
- 缺少项目/会话/运行身份：从真正的会话工具调用中测试；不要从前端当前页面、旧日志或参数里猜身份。
- 修改源码后需要重启后端；只新增使用已有能力的工具通常无需修改或重建前端。

### 扩展一个新的后端能力

以新增通用 `example_lookup` 为流程示意，这个名称目前没有实现，不能直接声明使用：

1. 找到现有业务 service，确定最小操作集合、输入输出、所需调用上下文和副作用。不为单个工具名字写后端特判。
2. 在 `app/domain/tools/host_capabilities.py` 增加枚举和注册表项，指定一个明确的 POST 路径及说明。SDK 映射、清单校验、网关精确路径列表会自动采用该项；**注册路径不会自动创建路由，更不代表匿名访问获准**。
3. 在 schemas 或对应独立路由模块定义请求合同，拒绝未知字段。不要提供“任意服务名/任意函数名/任意 Python”转发参数。完整描述合法值、错误与返回。
4. 在 `app/api/routes/` 实现并挂载端点。先解析 Bearer，调用 `HostCapabilityAccessService.authorize(token, 对应能力)`；无授权返回 401。调用方项目、会话、模型和运行身份取自 grant，不信任请求体冒充这些身份。可以参考 `app/api/routes/tools/host_capabilities.py`。
5. 调用现有业务服务，并校验该能力的范围、会话当前配置和实际目标。模型凭据、登录状态等由宿主解析和使用，结果不返回原始密钥。耗时同步工作不能直接阻塞 async 路由的事件循环。
6. 保持网关只允许注册的**精确 POST 路径**进入能力自己的认证；不要放开整个 `/api/tools`、`/api/projects` 或本机请求，不向工具发放全局网关凭据。
7. 在新工具 runtime.host_capabilities 中声明能力，通过 SDK 接入；如需后台租约，应单独设计最小权限、有效期、任务换代和撤销规则，不把普通工具 token 变成永久凭据。
8. 完成下面的验证，并更新本页清单、请求示例、源码导航与空白工具资料版本。重启后端验证真实链路；只有修改前端能力或界面时才需要同步构建前端。

必须覆盖：未授权、错误能力、过期、伪造上下文、禁用目标、工具改名/复制、失败或取消后的撤销、动态调用的目标范围。至少有一个测试从工具 SDK 经过真实网关中间件进入路由和服务，不能只 mock HTTP 返回成功。相关测试可参考 `tests/test_declared_host_capabilities.py`。

## 普通 HTTP 接口和桌面壳

浏览器 API 走现有 httpClient，遵守访问密码和认证；Python 工具默认没有浏览器 Cookie，本机 127.0.0.1 不代表免授权。确实需要宿主能力时按上文扩展，不能通过关安全设置解决。

桌面壳 API 是另一个边界，见 `3_PyWebView/app/api.py` 及前端 desktop 服务的实际定义；不是写个 client 能力名就能调用任意本机动作。桌面、浏览器和远程访问的能力可能不同，需要明确判断，不假定远程前端的电脑就是后端所在电脑。
