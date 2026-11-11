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
    "client_capability": {"name": "tool.projects", "min_version": 2}
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
| `editor.tabs` | 3 | 编辑器标签及文件内容定位，查看 editorTabsClientTool.ts、useDocumentReveal.ts；旧标签动作的后台项目处理见 backgroundEditorTabsClientTool.ts |
| `conversation.management` | 3 | 会话层级/分类查询、读取、创建、配置、删除预览、精确批量及递归删除，conversationManagementClientTool.ts |
| `conversation.interaction` | 1 | 向会话发送任务、等待等，conversationInteractionClientTool.ts |
| `tool.projects` | 2 | 工具分类、查询、新建、原地初始化、重命名、移动、开关与删除，toolProjectClientTool.ts |
| `role.projects` | 1 | 角色分类、查询、新建、原地初始化、重命名、移动与删除，roleProjectClientTool.ts |

以当前注册表为准，不能从这张表推断其他动作已开放。参数应读取对应工具 input.schema.json 和执行器，不要猜动作名。

### conversation.management v3：会话树与删除范围

每个会话都可以继续拥有 `child` AI 子会话、`fork` 历史分支，以及自动命名、记忆压缩、项目记忆管理、全局记忆管理四类功能会话，结构不限固定层数；分组标题不是会话。功能任务的防递归设置与树结构是两回事。

`list_sessions` 的 scope 支持 related/all/roots/children/descendants，session_id 指定关系中心，group/runtime_status 可筛选。行数据含 parent_session_id、group、depth、display_number、relation_kind、function_type、created_by、child_count；编号不是身份，始终用 session_id 操作。查询复用普通会话摘要接口和共享树构建规则。

`preview_delete`/`delete_session` 使用 session_id 或 session_ids（二选一），include_descendants 默认 false。true 才展开目标全部后代；保留下级沿存活祖先重新挂接。预览只读；执行需 confirm=true。严格按预览执行时，把返回的完整 session_ids 配合 include_descendants=false 传回，避免新建后代改变范围。调用者及其祖先受保护，删除结果返回实际删除 ID；不会撤销已经提交的记忆等产物。

新增批量 API 是通用项目会话接口 `DELETE /api/projects/{project_id}/conversations`，接收明确 session_ids 和可选 protected_session_id，复用原删除流程；不是按工具名添加的后端专用入口。工具运行时使用请求中的 project_id/session_id，不跟随当前界面选择。使用 v2 参数需在工具清单中设置 min_version=2；旧客户端不会降级忽略参数。

### editor.tabs v3：标签与内容定位

标准工具调用名为 `editor_tabs_manager`。`list_tabs`、`open_file`、`focus_file`、`close_clean_tabs`、`close_others_clean` 保持原有语义；v2 引入 `reveal_file`，v3 保留单目标参数并增加文本多范围。工具清单引用 `{"name":"editor.tabs","min_version":3}`，使用 `client_json` 输入输出，不需要 Python 程序或新增后端业务路由。仅声明能力不会给旧前端增加实现，必须部署带 v3 执行器的前端。

`reveal_file` 必填 `path` 和 `target`，不接受批量 `paths`。path 是调用方项目中的相对路径，示例使用 `/`；项目身份取自请求的 `project_id`，不能通过参数指定或回退为其他项目。target 只接受下面一种结构，不混用字段：

| target.type | 必填字段 | 可选字段 | 含义 |
| --- | --- | --- | --- |
| `pdf_page` | `page` | 无 | PDF 页码，从 1 开始 |
| `line_range` | `start_line`、`end_line` | 无 | 文本行号从 1 开始，含首尾行；end_line 不小于 start_line |
| `text` | `text` | `occurrence` | 非空原文精确匹配；重复时必须指定第几处，从 1 开始 |
| `text_ranges` | `ranges` | 无 | 非空数组，数量不设上限；元素为上面的 text 或 line_range，可以混合，不接受 PDF 或嵌套多范围 |

```json
{"action":"reveal_file","path":"reports/report.pdf","target":{"type":"pdf_page","page":8}}
```

```json
{"action":"reveal_file","path":"src/main.py","target":{"type":"line_range","start_line":20,"end_line":35}}
```

```json
{"action":"reveal_file","path":"docs/report.md","target":{"type":"text","text":"本季度销售额增长 12%"}}
```

```json
{"action":"reveal_file","path":"src/main.py","target":{"type":"text","text":"return result","occurrence":2}}
```

混合多范围，先展示输入的第一项（第 40 至 48 行），不是自动选择文件中位置最靠前的那一项：

```json
{"action":"reveal_file","path":"src/main.py","target":{"type":"text_ranges","ranges":[{"type":"line_range","start_line":40,"end_line":48},{"type":"text","text":"return result","occurrence":2},{"type":"line_range","start_line":5,"end_line":8}]}}
```

执行与结果约定：

- 未打开时打开文件，已打开时复用标签，已处于该标签时仍执行本次定位。不会另建重复标签，不为定位重新覆盖已打开文本的内容。
- 文本定位以 CodeMirror 当前缓冲区为准，包括未保存及尚未经过输入防抖同步的文字；不拿磁盘内容计算位置。保留首尾空白、区分大小写，仅将 CRLF/CR 换行统一为 LF。按位置计数，包括重叠匹配；多处匹配且未指定 occurrence 时拒绝猜选。
- 使用编辑器原生选区高亮并居中显示，不插入标记、不修改文件、不因为选中而产生脏状态。Markdown/HTML 切到源码模式，行号和原文均针对源码；它不是 Word 段落、表格单元格或渲染后 Markdown 的选区接口。
- 多范围先针对同一个实时缓冲区完整解析，全部成功后一次性建立多选区；从输入 ranges[0] 居中展示，以其所在选区作为主选区。CodeMirror 会按文档位置整理选区，并合并重叠或重复范围，但不改变“先展示第一项”的约定。Schema 不设 maxItems，前端不按固定条数截断。任一项失败则整批不应用，返回从 1 开始的 range_index；保留原来的选区，不忽略失败项。
- 页码定位等待 PDF 加载、页数检查及目标页实际渲染完成。文本定位等待编辑器选区应用，并检查内容和选区未被中途改变。历史阅读位置恢复不会把这次定位覆盖回去。
- 仅在调用方项目就是当前编辑器前台项目时执行；后台项目返回 `PROJECT_NOT_ACTIVE`，不能把后台工作区标签记录更新冒充已展示。旧标签动作的后台处理不等于内容定位能力。
- `pdf_page` 只支持 PDF；文本目标只支持当前以文本编辑器打开的文件，如 TXT、代码、JSON、Markdown、HTML。CSV/TSV 当前走表格预览，与 Word、Excel、PPT、图片等一样不支持这项文本选区合同，不支持时返回 `UNSUPPORTED_TARGET`。
- 能打开 Office 不代表能在 Office 里定位文字。标准工具的摘要、action/path/target 和显式注入的短说明共同声明此边界。`UNSUPPORTED_TARGET` 另带 file_kind、requested_target、supported_target_types 和 suggested_action；Office 的 supported_target_types 为空，只能建议 open_file 展示完整文件，不得换一段原文/行号反复重试，也不能将打开预览称为已选中。开发资料本身不会自动进入模型上下文。
- 成功结果包含 `ok:true`、`action`、`path`、`displayed:true`、`location`、`revealed_tab`。PDF location 返回 page/total_pages；文本返回 `type:"text_selection"`、行列范围、from/to、`source:"editor_buffer"`，原文匹配另带 match_count/occurrence。行列从 1 开始；from/to 是从 0 开始的 UTF-16 偏移，to 与 end_column 为结束边界、不包含该位置。输入行范围含首尾行文字，不额外选入末行后的换行。
- 多范围 location 返回 `type:"text_selections"`、`source:"editor_buffer"`、ranges；ranges 按输入顺序逐项返回上述 text_selection 结构，即使实际高亮被合并也保留每项结果。单目标的输入及返回结构保持不变。
- target 结构或数值非法返回 `INVALID_TARGET`。`TEXT_NOT_FOUND`、`AMBIGUOUS_TEXT`、`OCCURRENCE_OUT_OF_RANGE`、`LINE_OUT_OF_RANGE`、`PAGE_OUT_OF_RANGE` 返回明确失败，必要时带 match_count、total_lines 或 total_pages。加载、渲染和预览受限分别返回 `LOAD_FAILED`、`RENDER_FAILED`、`PREVIEW_UNAVAILABLE`/`CONTENT_UNAVAILABLE`；标签被标记为不存在且没有未保存内容时返回 `FILE_NOT_FOUND`，预览层先检测到资源不可用时也可能返回 `PREVIEW_UNAVAILABLE`。
- 前端响应 signal 取消，标签关闭或切换返回 `NAVIGATION_INTERRUPTED`；同一编辑器的新定位替代旧请求，旧请求返回 `SUPERSEDED`；定位期间内容或选区变化返回 `SELECTION_CHANGED`。内部等待上限 30 秒，未确认显示返回 `REVEAL_TIMEOUT`，仍受工具清单及通用桥的总时间预算限制。取消不回滚已经打开的标签或已发生的界面移动。

参数和结果以标准工具 `.tool/input.schema.json`、`.tool/output.schema.json` 为准；`target` 与其他界面操作参数同属 `ui_control`。扩展定位类型时，须一起修改桥合同、对应渲染器、输入输出 Schema、示例和本资料，不能只往工具参数中增加前端未实现的字段。

### tool.projects v2 与 role.projects v1

`tool.projects` 提供 list_categories/create_category/list/get/create_tool/initialize_current/rename/move/delete/set_state；`role.projects` 提供相同管理动作，创建动作为 create_role，没有 set_state。读取参数 Schema 获取各动作必填字段；不能用分类名称代替 ID。

模板由执行工具自己的 `assets/scaffold.json` 描述。索引 version=1、template_version 为字符串、documentation 为生成后的资料路径、files 为 source/target 数组。工具模板包含五份标准 JSON 与 program/main.py；角色模板包含八份配置 JSON。目标不能是 `.Tiance`。所有内容读取及校验完成后才创建项目。

initialize_current 绑定 request.project_id，不使用界面活动项目。后端统一检查登记的集、分类和真实目录必须对应，拒绝符号链接/junction，整组补缺失败回滚；已有文件不覆盖。工具新清单强制 state.enabled=false；初始化既有清单返回其真实开关。模板不在前端源码内硬编码，说明与程序一起存放于工具项目。

使用已有项目/分类/角色/工具生命周期 API；批量初始化接口为 `POST /api/projects/{id}/files/scaffold`，body 为 `{project_kind, files:[{path,content}]}`。它复用项目文件事务，只接收 tool/role/theme 三种集。角色完整配置查询为 `GET /api/projects/roles/{id}/configuration`。前端沿用已认证的 httpClient，不向工具暴露登录凭据。完成后通知目录刷新，不切换用户项目。

创建失败时保留已知项目身份；若响应丢失，先查询核实。不能盲目重建，也不能把系统回收站操作描述为可数据库回滚。delete 拒绝当前调用项目和正在执行的管理工具。用户已有文件通过普通文件工具编辑，不因模板更新而自动替换。

### 会话角色选择与复刻

`create_session`、`clone_session`、`configure_session` 共用 configuration：role_project_id 选完整角色（包括模型），不传则以来源/目标会话为基础；model_source=caller 只取调用者的模型和思考模式；显式 provider_id/model_id 必须成对且不能与 caller 来源同时传入；显式 settings 等覆盖基础。先校验再单次写入，覆盖后的配置不回写角色模板。

clone_session 使用调用会话为源，默认选最后一条已完成用户消息，也可传 source_message_id。复用用户编辑分支流程：复制该消息之前的历史、附件和记忆交付快照，该消息及引用留在新会话草稿。分组关系是 AI 子会话（child/ai），历史类型为 fork。创建不自动运行或切换；当前工具调用所在回合不被复制。后续用会话交互工具发送新任务。源会话继续执行，派生内容不追随其后续写入。

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
| `conversation_naming` | `/tools/capabilities/conversation-naming` | 自动命名功能会话向其来源会话提交标题；目标取自授权与分支关系 |
| `tool_catalog` | `/tools/capabilities/catalog` | 读取本次调用范围内工具的参数和案例 |
| `external_messaging` | `/tools/capabilities/external-messaging` | 列出脱敏机器人连接，向显式目标聊天发送文件；当前实现 Telegram |
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

自动命名的提交示例：`call_host_capability("conversation_naming", {"title": "订单汇总与核对"}, timeout_seconds=30)`。请求只接收 title，不能传入项目或会话 ID；当前调用必须属于有效的自动命名功能会话，后端核对任务、父节点和手动命名状态。普通会话即使声明此能力也不能冒充命名任务。标准工具是 `submit_conversation_title`，不再通过前端会话管理动作提交。工具的普通启用、参数权限和执行时限仍然生效。

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


### 第三方机器人文件发送

`external_messaging` 使用已配置的连接，不向工具暴露 Token。`platform` 支持 `telegram`、`feishu`、`wechat`；`action` 为 `list_connections` / `send_file`，发送时再传 `connection_id`、`chat_id`、绝对 `file_path`，可选 `caption`。微信还要求指定接收者曾发消息取得有效回复凭据。消息 ID 可能为数字或字符串，不能按 Telegram 的数字格式限制其他平台。独立工具自行解析相对路径。例：

```python
call_host_capability("external_messaging", {
    "platform": "telegram", "action": "send_file",
    "connection_id": "telegram:123456", "chat_id": "987654321",
    "file_path": "C:/work/report.docx", "caption": "请查收报告。"
}, timeout_seconds=600)
```

示例 ID 必须换成实际目标；工具可先用 `list_connections` 查询，手机用户消息正文也会标注来源。后端不要求目标等于上个发送者，不要求由手机任务发起；普通工具参数应准确标注 `filesystem_read`、`credential_use`、`external_data_modify` 和 `network_access`，不能省略发送目标授权。连接本身须已启用，Telegram 也须允许向该聊天投递。

`sent` 才是全部确认，`not_sent` 是明确失败，`unknown` 需核对是否已送达，`partial` 需查看已确认消息 ID 并避免重传文件。没有自动重试或无限等待；超时遵守工具与网络配置。不要用宽泛 except 把 unknown 改成“未发送”。凭据只由后端适配器读取。未来增加平台在 `app/services/mobile/manager.py` 与 `messaging.py` 注册适配器，通用连接表、作用域查询、授权与会话运行保持共用；独立工具是否扩展平台由工具作者决定。
