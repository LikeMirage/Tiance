# 06 当前应用源码导航

以下路径相对**天策应用源码根目录**，不是新工具项目根。先在当前安装位置找到同时包含 `1_PythonServer`、`2_ReactWeb`、`3_PyWebView` 和 `system/version.json` 的目录；默认工具路径为该根下 `Data/tools/<UUID>`，自定义数据目录时不要机械截取父目录猜应用位置。当前应用保留源码，可用文件搜索和 rg 定位。不要为查找源码打开或输出密钥文件。

## 后端

| 路径 | 关注点 |
| --- | --- |
| `1_PythonServer/app/services/application/project_creation.py` | 创建项目、初始会话、失败回滚 |
| `1_PythonServer/app/services/tools/tool_projects.py` | 工具分类/项目与统一项目服务的桥接 |
| `1_PythonServer/app/services/tools/toolsets.py` | 三个开关保存和注册刷新 |
| `1_PythonServer/app/repositories/project/file_project_catalog.py` | 文件式项目目录，不直接编辑代替服务 |
| `1_PythonServer/app/infra/tools/tool_project_config_constants.py` | 标准文件名与位置 |
| `1_PythonServer/app/infra/tools/tool_project_config_storage.py`、`tool_project_config_helpers.py` | 配置标准化、必填和旧字段处理 |
| `1_PythonServer/app/services/tools/tool_metadata.py`、`tool_registry.py` | 加载、唯一性、注册快照 |
| `1_PythonServer/app/services/tools/chat_tool_injection.py`、`dynamic_tool_contract.py` | 真实模型注入和动态加载 |
| `1_PythonServer/app/services/tools/tool_execution.py`、`tool_execution_arguments.py` | 分发、参数校验、客户端准备、宿主凭据签发 |
| `1_PythonServer/app/services/tools/tool_execution_runtime.py`、`tool_execution_results.py` | 进程环境、cwd、终止、JSON 结果解析 |
| `1_PythonServer/tiance_runtime.py` | run_tool、模型模态、call_host_capability |
| `1_PythonServer/app/services/tools/tool_result_content.py`、`tool_resource_uris.py` | 图片内容块和受控 URI |
| `1_PythonServer/app/domain/tools/parameter_permissions.py`、`permission_policies.py` | 权限类型、范围、默认策略 |
| `1_PythonServer/app/services/tools/tool_permissions.py`、`tool_permission_bridge.py` | 决策、询问与生命周期 |
| `1_PythonServer/app/services/tools/client_tool_bridge.py` | 请求、租约、提交、重放和取消 |
| `1_PythonServer/app/domain/llm/chat.py` | ChatClientToolRequest 等内部合同 |
| `1_PythonServer/app/services/project/conversation_tool_loop.py`、`conversation_stream_events.py` | 统一执行循环及前端事件序列化 |
| `1_PythonServer/app/services/tools/host_capability_access.py` | 宿主能力枚举、工具允许名单和过期凭据 |
| `1_PythonServer/app/api/routes/llm/provider_capabilities.py` | 搜索能力授权端点 |
| `1_PythonServer/app/api/routes/tools/toolsets.py`、`tool_folder_files.py` | 分类、项目、文件 HTTP 合同 |
| `1_PythonServer/app/services/application/tool_market.py` | 安装、更新、本地设置保留和回滚 |
| `1_PythonServer/app/services/tools/tool_dependency_runtime.py` | 私有依赖环境实际定位 |

同一表格中只写文件名的后续项与第一个文件同目录。用函数名进一步定位，不依赖会变动的行号。

## 前端和桌面

| 路径 | 关注点 |
| --- | --- |
| `2_ReactWeb/src/features/client-tools/model/clientToolBridge.ts` | 能力名称/版本登记，不按工具名分发 |
| `2_ReactWeb/src/features/client-tools/model/clientToolRequestSingleFlight.ts`、`clientToolExecutionSession.ts` | 跨窗口领取与执行证据 |
| `2_ReactWeb/src/features/ai-panel/model/useChatPanelClientToolRegistry.ts` | 能力组合和后台会话复用 |
| `2_ReactWeb/src/features/client-tools/model/toolProjectClientTool.ts`、`toolProjectScaffold.ts` | 分类和模板创建能力，模板文件最后发布清单 |
| `2_ReactWeb/src/features/client-tools/model/conversationManagementClientTool.ts`、`conversationInteractionClientTool.ts` | 复用现有 API 的 client 示例 |
| `2_ReactWeb/src/features/client-tools/model/editorTabsClientTool.ts` | 依赖真实前端状态的能力示例 |
| `2_ReactWeb/src/entities/llm-chat/model/chatCompletion.ts` | 前端请求字段与后端合同对应 |
| `2_ReactWeb/src/services/http/httpClient.ts` | API 基址、认证、错误处理 |
| `2_ReactWeb/src/services/tools/` | 现成分类/项目/文件/依赖/市场接口 |
| `2_ReactWeb/src/entities/tool/model/toolCatalogEvents.ts` | 工具列表与元数据刷新通知 |
| `2_ReactWeb/src/shared/types/desktopShell.ts`、`src/services/desktop/` | 桌面壳能力声明和调用（第二个路径相对 2_ReactWeb） |
| `3_PyWebView/app/` | 壳侧实际实现；用 ShellApi 类名检索当前文件 |

## 可参考的真实工具

工具 ID 可能变化，先通过工具集目录定位项目，再阅读 `.tool/tool.json` 的 name 来确认身份，不把历史 UUID 写死进程序。可按调用名查找 network_search、deepseek_official_web_search、manage_memory、manage_ai_conversations、interact_ai_conversation、read_text_file 等。检索时仅扫描工具清单和源码，不把整个 Data 或 config.json 的凭据打印出来。

## 测试入口

- 后端 `tests/test_tool_registry.py`、`test_tool_project_config_storage.py`、`test_tool_execution.py`、`test_tool_execution_arguments.py`、`test_tiance_runtime.py`。
- 后端 `tests/test_project_creation_application.py`、`test_conversation_run_manager.py`、`test_tool_permission_runtime.py`、`test_tool_project_scaffolder.py`。
- 前端 `tests/tool-project-client-tool.test.mjs`、`client-tool-bridge.test.mjs`、`client-tool-request-single-flight.test.mjs`、`conversation-management-client-tool-registration.test.mjs`。

测试目录分别相对 1_PythonServer 和 2_ReactWeb。使用对应项目的依赖环境运行；前后端当前命令以 pyproject.toml、package.json 为准。优先运行与实际变更相关的测试，而非把“能导入模块”当作功能验证。
