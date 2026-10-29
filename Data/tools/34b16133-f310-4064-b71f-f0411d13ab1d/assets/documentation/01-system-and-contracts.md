# 01 系统与配置合同

## 一切都是项目

工具项目与普通项目共用项目、分类、会话、编辑器和文件能力。默认位于 `Data/tools/<项目 UUID>/`，分类只是逻辑分类，不再多套一层文件夹。根目录 `Data/tools/catalog.json` 保存分类、项目 ID、项目名称和排序，工具实际调用合同在各自 `.tool` 中。仅创建磁盘文件夹不会完成项目登记；请复用产品项目创建服务。

三个身份不能混用：项目 UUID 管生命周期和目录；`.tool/tool.json.name` 是模型调用名；根目录市场 `manifest.json.id` 是包更新身份。`registration_name` 是工具注册显示名，项目列表的名称与它独立，不要因为改显示文字就生成新 UUID 或市场 ID。

## 标准目录

```text
工具项目/
  .tool/
    tool.json
    input.schema.json
    output.schema.json
    examples.json
    permissions.json
  program/
    main.py
    config.json
    requirements.txt
  docs/tool-development/
  tests/
  assets/                 按需创建
  dependencies/           由依赖安装器管理
  .Tiance/                天策工作区，不能当程序配置
```

本地工具不要求市场 `manifest.json`。`.tool/workspace.json` 的常量存在于源码，但不是注册必需文件，不要为了“齐全”编造内容。

## tool.json

本项目已有一份合法清单，优先编辑它。各字段含义：

| 字段 | 含义与要求 |
| --- | --- |
| `name` | 当前工具空间内唯一的稳定调用名。本创建器接受 1–64 位英文、数字、下划线，首位不是数字 |
| `registration_name` | 非空注册显示名称 |
| `description` | 用途、适用场景和关键限制；不粘贴整本手册 |
| `state.enabled` | 全局开关；新工具必须为 false，完成后按用户意愿开启 |
| `loading.dynamic` | 初始只注入轻量目录，具体参数按需读取 |
| `execution.parallel` | 必填布尔值；是否允许平台并发派发这个工具。共享写入、顺序依赖时关闭；关闭也不替代程序自己的锁与跨会话互斥 |
| `runtime.type` | 普通扩展使用 python 或 client；internal 是平台基础设施，不是插件入口 |
| `runtime.entry` | Python 程序的项目内相对路径，模板为 program/main.py |
| `runtime.timeout_seconds` | 必填正整数，按真实任务预算设置 |
| `runtime.host_capabilities` | Python 专用，可选能力名称数组；默认空，只申请实际需要的后端能力，不绑定工具调用名；详见 04 |
| `runtime.client_capability` | client 专用，包含能力 name 与正整数 min_version，必须实际注册 |
| `io` | 约定说明：Python 用 stdin_json/stdout_json；client 用 client_json/client_json |
| `files` | 固定指向 .tool 下的输入、输出、案例、权限四份文件；保存时会标准化 |

开关仍在本工具的 tool.json 中，没有另设全局工具设置表。不要增加已删除的工具关键词、旧式内嵌参数和旧 context/capabilities/ui 配置；源码标准化会移除若干旧字段，未被移除不代表运行时会使用。

## 输入 Schema

根部为 `type: object`，使用 `properties`、`required`、`additionalProperties` 描述真实接口。参数说明放在该参数 `description`；根部 `description` 可以解释跨参数关系，不必复述所有参数。工具摘要、参数说明、案例内容不能相互矛盾。

```json
{
  "type": "object",
  "properties": {
    "path": { "type": "string", "minLength": 1, "description": "待读取的文件路径。", "permission_type": "filesystem_read" },
    "encoding": { "type": "string", "enum": ["utf-8", "utf-8-sig"], "description": "省略时使用 utf-8。", "permission_type": "none" }
  },
  "required": ["path"],
  "additionalProperties": false
}
```

这是演示，不要给空白工具照搬未实现参数。Schema 的 default 是说明性声明，不能假定平台会把它自动填进程序收到的参数；程序须显式实现同样的默认行为。不要静默截断用户输入。

当前校验器支持常见类型、必填、枚举、常量、长度与数值限制、pattern、数组项、additionalProperties，以及本地 $ref、allOf/anyOf/oneOf、if/then/else、not 等组合。它不是完整 JSON Schema 标准实现，新增复杂规则应检查 `tool_execution_arguments.py` 并写正反例测试。权限元数据只在顶层 properties 中解释和剥离，见权限章节。

一个已知实现限制：oneOf 命中后会直接返回该分支的验证结果，不继续校验同层其他约束。需要同时校验顶层类型、额外字段和分支时，可把 oneOf 放进 allOf 的子项，让共同约束留在外层，并使用真实校验器验证。创建器自身的 Schema 采用此结构；不要只拿通用 JSON Schema 库的通过结果推断平台行为。

## 输出 Schema 与标准结果

output.schema.json 应描述真实返回。Python stdout 必须是 JSON 对象；退出码为 0 且 ok 不为 false 才会判为成功。当前执行器不会按 output.schema.json 对每个返回字段做完整校验，仍需自己的契约测试。client 执行器内部返回 `{ok, content, error}`；content 是对象时，平台将该对象的字段展开到最终结果根部并补入 ok/error。output Schema 应描述展开后的模型结果，而不是前端内部包装。

建议结果包含 ok、简短 summary、结构化 data；失败包含 error 和可判定错误码。文件路径是合法结果信息，用户需要它来继续工作；图片应额外使用标准资源内容块，不能只给路径并声称模型已看见。

## 案例

examples.json 是数组，条目为 `{ "title": "名称", "content": "说明和真实参数示例", "enabled": true, "inject_content": false }`。已启用标题会进入目录/说明，正文只有明确开启 inject_content 才注入。正文默认按需读取，可减少上下文占用。不要增加程序尚不支持的操作。

## 注册、注入和调用

1. 按工具分类和项目目录读取清单；没有 tool.json 的空白项目被跳过。
2. 清单存在就读取输入、输出和案例。即使 enabled=false，也必须是完整有效配置。调用名冲突或单个配置损坏可能导致整次注册表刷新失败，保留之前的索引；不能把改文件等同于刷新成功。
3. 标准加载注入调用名、组合说明和去掉权限元数据的输入 Schema；输出 Schema 不作为模型输入参数注入。
4. 动态加载先提供轻量目录，通过 load_tool_info 获取详细参数/案例，再由 execute_dynamic_tool 转交。动态目标仍检查启用、会话选择、参数和权限，不是绕过工具边界的方法。
5. 执行前校验参数、权限与运行配置；分发到 Python 子进程或已登记的 client 能力；结果回到统一工具循环。

创建完整模板应最后发布 tool.json；更新已有工具时也要保证各份合同一致，不能假定单纯关闭开关就允许缺失 Schema。文件监听会刷新元数据，但它是异步的；保存接口遇到注册错误会返回失败。工具调用审计在工具项目 `.Tiance/tool-calls/records.jsonl`，调用方会话还会保存正式工具消息。
