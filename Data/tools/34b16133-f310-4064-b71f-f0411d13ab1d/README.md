# 新建空白工具

调用名：`create_blank_tool`。使用前端 `tool.projects v1` 能力，复用已有分类、项目和文件接口。

- `list_categories` 查看分类。
- `create_category` 按 name 创建分类。
- `create_tool` 按 category_id、name 创建完整工具模板；可选 call_name。

新工具包含五份 `.tool` 配置、Python 入口、业务配置、依赖声明、测试示例和完整制作资料。默认关闭。结果返回项目路径、文档入口和启用说明，要求制作前阅读资料、完成后根据用户意愿决定是否启用。

## 模板与资料维护

- `assets/scaffold.json`：复制清单与模板版本。
- `assets/template/`：创建时使用的通用配置和程序模板。
- `assets/documentation/`：工具制作资料；复制到新工具的 `docs/tool-development/`。

修改模板或资料后应同步验证整套文件，并更新 template_version。已有项目保留创建时的资料快照。本创建器的前端实现位于应用源码 `2_ReactWeb/src/features/client-tools/model/toolProjectClientTool.ts` 和 `toolProjectScaffold.ts`；模板和资料不写死在前端代码中。

工具需要前端在线，并使用携带 tool_project_id 的新版通用能力桥。更新程序后重启应用再使用。创建动作不切换用户当前项目；失败返回部分完成状态，不自动删除项目或重复创建。
