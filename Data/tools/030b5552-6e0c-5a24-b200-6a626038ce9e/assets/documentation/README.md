# 天策角色制作说明

角色是配置模板，不是单独的 AI 引擎或后端权限。角色项目与普通项目一样有文件夹和独立会话；制作角色的会话配置与正在编辑的角色文件不是同一份数据。

## 开始制作

先确认当前工作区和用户目标。`manage_roles` 支持分类查询/创建、角色列表/详情、新建、原地初始化、重命名、移动和删除。

- 新建用 `create_role(name, category_id)`，沿用界面创建角色的流程：角色文件来自基础默认角色；协助制作的首个会话使用设定集中角色集的默认角色。
- 已有角色项目用 `initialize_current`。必须在角色集已登记项目的根目录，不能向普通项目、工具项目或任意路径写模板。检查登记类型、分类和实际目录，拒绝目录链接。只补齐缺失文件，不覆盖现有文件或 `.Tiance`。
- `get(project_id)` 返回各配置文件及应用后完整配置。不要把工作会话的提示词直接写成目标角色提示词，除非用户明确要求复制。
- 创建结果未知时先 `list` 查找，已创建但资料不全时在同一项目补齐，不能盲目重建。

## 八份标准文件

| 文件 | 保存内容 |
| --- | --- |
| profile.json | description，角色用途说明；项目显示名称由项目登记管理 |
| model.json | provider_id、model_id、reasoning_mode；供应商和模型必须成对配置，使用真实 ID，不写密钥 |
| generation.json | temperature、top_p、max_output_tokens；先查询目标模型可用能力 |
| prompt.json | system_prompt；职责、工作步骤、资料入口和边界 |
| response.json | 自动命名、流式、过程折叠、工具格式恢复、重试次数/间隔、输出上限处理 |
| context.json | inject_message_timestamps |
| memory.json | 全局/项目记忆注入与提取开关、压缩开关、触发阈值、保留原文量 |
| tools.json | tools_enabled、enabled_tool_names、max_tool_calls、tool_approval_mode |

保留文件中既有合法字段。以 `get` 返回的配置与当前平台 Schema 为准，不自行编造字段。模型 ID 不同于显示名称；使用 AI 会话管理工具的 `query_models` 查询。工具名使用真实调用名称；动态加载仍受会话工具选择和权限约束。

编辑用普通文件读取和编辑工具，保存合法 JSON。前端设置页的保存走同一文件合同。用户修改配置应优先于默认值，不偷偷开启其他功能或更换模型。多文件一起改时使用已有批量文件保存接口以保持失败回滚；若文件在外部被修改，重新读取后合并。

## 在会话中使用

AI 会话管理工具的 `configuration.role_project_id` 选择完整角色配置（包括模型），然后 `configuration.settings` 等显式字段覆盖。`model_source=caller` 仅继承调用者的供应商、模型及思考模式；也可以显式指定 provider_id 与 model_id。显式 reasoning_mode 最后生效。角色未配可用模型时需选择模型。覆盖后的会话可以成为自定义配置，不反向修改角色模板。

普通创建不带历史。`clone_session` 走编辑用户消息的分支复制流程，默认以最后一条用户消息为分界：此前历史复制，该消息与引用进入草稿；归 AI 子会话，创建后不自动运行或切换。角色选择和历史复制相互独立。

角色模板修改不会自动重写已有会话。修改已有会话请显式 `configure_session` 或使用会话设置中的角色选择。默认角色归属在设定集逐个集配置，不能在工具或后端按角色名称写死。

## 删除、验证与源码

删除前核对 ID、名称、路径和用户意愿。`delete(project_id, confirm=true)` 使用平台项目删除流程，托管文件夹连同会话、附件进入系统回收站；本次调用所在项目不能删除。删除角色不会删除使用过它的会话配置快照。

验证八个 JSON 均可解析，设置面板能读取，模型/思考/采样匹配；在新会话应用角色核对完整设置，确认角色文件与其他会话没有被改写。不要用真实用户的会话做删除试验。

源码相对安装目录：

- `1_PythonServer/app/services/application/role_configuration.py`：默认角色、读取、应用、保存和角色初始化。
- `1_PythonServer/app/services/application/conversation_configuration.py`：角色基础与会话显式覆盖。
- `1_PythonServer/app/services/application/project_scaffold.py`：集与路径检查、缺失文件初始化。
- `1_PythonServer/app/domain/project/project_conversation.py` 与 `app/schemas/project/project_conversations.py`：会话设置与校验。
- `2_ReactWeb/src/entities/role-configuration/model/roleConfiguration.ts`：角色文件格式与界面解析。
- `2_ReactWeb/src/features/client-tools/model/roleProjectClientTool.ts`：`role.projects v1`，通过普通项目/角色接口工作。

能力不足时扩展通用接口/能力桥及 Schema、文档和验证；不要把角色名写进运行引擎。需要新增工具时使用工具管理工具及其制作资料。
