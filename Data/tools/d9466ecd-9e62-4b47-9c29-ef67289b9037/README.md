# 系统文件打开

调用名：`open_system_file`。独立 Windows Python 工具，无第三方依赖，不依赖天策前端在线，不导入后端业务模块。

| action | 行为 |
| --- | --- |
| `reveal` | 在资源管理器中选中文件；目录路径则打开目录本身 |
| `get_default_app` | 查询文件扩展名的当前默认应用，不打开窗口 |
| `list_apps` | 实时枚举系统“打开方式”，返回稳定应用标识、名称、默认及推荐标记 |
| `open_default` | 使用系统当前默认关联打开文件，不优先挑选 Office/WPS |
| `open_with` | 用列表的应用标识或明确的 EXE/COM 路径打开一次，不改变默认关联 |

所有动作必填 `action`、`path`。路径可以是调用工作区相对路径或本机绝对路径，支持中文和空格。相对路径必须有 `TIANCE_WORKSPACE_ROOT`，不会回退到工具目录。仅 `reveal` 接受文件夹。路径须实际存在；不接受 URL、Shell 命令、备用数据流、盘符相对路径。

```json
{"action":"list_apps","path":"配置.json"}
```

从返回的 `applications` 取 `application_id` 原样传给 `open_with`，不能传显示名称，也不能把其他扩展名的标识挪过来。标识失效时重新查询。

```json
{"action":"open_with","path":"配置.json","application_path":"C:/Windows/System32/notepad.exe"}
```

`application_id` 与 `application_path` 二选一，仅供 `open_with` 使用。程序路径必须是已存在的 EXE/COM 绝对路径；使用参数数组传入文件，不拼接 Shell，不接受自定义命令行和附加参数。应用进程不继承天策能力凭据或 Python 启动环境。

## 结果和限制

- `queried`：完成查询；`submitted`：系统接受打开请求。后者不证明窗口已显示、文档已加载或内容已读取，也不会等待应用关闭。
- 窗口出现在运行天策的电脑上。微信、飞书、Telegram 调用不会在手机上打开附件。
- 候选是 Windows 登记的打开方式，包含推荐项和其他候选；不保证每个候选都能解析内容，也不保证包含所有实际兼容的软件。优先参考 `recommended`，未列出的应用仍可通过程序路径打开。
- `is_default=null` 表示无法可靠识别该候选是否为默认项；不按显示名称猜测。默认关联可能没有普通 EXE 路径，保留系统 ProgID/AppUserModelID。
- 无扩展名文件无法按扩展名枚举，返回空列表和说明，可以指定程序打开。未注册扩展名可能仍有 Windows 通用候选。
- 有些卸载残留或异常关联不能读取，结果在 `warnings` 汇总数量及错误码，`enumeration_complete=false`。可用项正常返回，不静默丢失异常。
- 默认打开无关联、程序不存在、系统拒绝或关联标识失效时返回结构化错误，不自动改用其他应用。打开后的取消不能撤回已发生的窗口动作；超时或结果未知时不要自动重试。

## 权限与部署

沿用天策参数权限系统。`path` 为文件读取权限，`application_path` 为程序执行权限；平台目前不按 action 分支计算权限，因此必填 `action` 保守声明系统程序执行权限，两个查询动作也经过该策略。默认策略允许读取、程序执行为 ask，实际是否询问由会话审批模式决定。工具不会修改本机默认应用、安装软件或提升权限。

工具全局启用与会话是否选用独立；不批量改动角色和已有会话的工具选择。无需重新编译前端。此目录是本地工具项目，不包含市场发布身份或用户许可证声明。

## 验证

在工具根目录运行 `python -m unittest discover -s tests -v`。测试可从当前天策工作区找到宿主校验器，仅测试代码使用后端模块；工具运行只用标准库和 `tiance_runtime.run_tool`。

2026-11-18 本机验证：19 项测试中 18 项通过，符号链接测试因 Windows 创建链接权限不足跳过。通过天策真实工具执行器及内嵌 Python，完成默认应用查询、打开方式枚举、默认打开、应用标识打开、EXE 路径打开、目录打开及文件选中。三个临时文档对应的记事本窗口均已出现，资源管理器选择对象与目标路径一致；操作前后默认关联相同。运行中的后端工具目录已识别并启用本工具。

原生实现依据：[SHAssocEnumHandlers](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-shassocenumhandlers)、[IAssocHandler](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-iassochandler)、[AssocQueryString](https://learn.microsoft.com/en-us/windows/win32/api/shlwapi/nf-shlwapi-assocquerystringw)。
