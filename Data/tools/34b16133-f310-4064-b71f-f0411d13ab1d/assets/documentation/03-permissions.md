# 03 参数权限、策略与副作用

## 权限由两个文件协作

input.schema.json 顶层 properties 中每个参数可写 `permission_type`，说明这个参数代表哪类能力；可写 `permission_scope` 声明此类型已有的固定范围。`.tool/permissions.json` 保存对应类型、范围的 deny / ask / allow。

权限类型和固定范围属于工具定义，不能作为模型参数让模型自己选择。平台发送输入 Schema 给模型前会去掉这两个元数据字段；它们不是给模型看的使用说明。

一次调用会汇总实际传入的各顶层参数，取最严格决定：deny > ask > allow。省略参数不会贡献权限事实；必要副作用必须有必填的、准确标注权限的参数。嵌套对象中的元数据不会自动变成独立授权，不能把危险操作藏进嵌套字段而把外层标 none。

## 类型和范围

| permission_type | 可用范围 |
| --- | --- |
| `none` | 不参与权限判断；只用于真正的普通控制值 |
| `filesystem_read` / `filesystem_write` / `filesystem_delete` | workspace_inside、workspace_outside、unresolved |
| `program_execute` | workspace_program、system_program、unresolved |
| `process_control` / `runtime_modify` | all |
| `network_access` | loopback、private_network、public_network、unresolved |
| `credential_use` | all |
| `external_data_read` / `external_data_modify` | all |
| `tiance_data_read` / `tiance_data_write` / `tiance_data_delete` | current_project、other_project、global_data、unresolved |
| `ui_control` | all |

未声明的参数进入 unknown，不等同于 none。未声明固定范围时，执行层从参数值与调用上下文判断；例如路径用工作区判断、URL 用地址判断。分类名、搜索词等本来就不是路径/主机/项目 ID，必要时使用准确的固定范围，不要为了躲开无法识别目标而改为 none。

新建工具模板携带平台当前完整默认策略：一般允许读取；工作区写入通常允许；跨工作区写入、凭据、环境修改和全局天策写入通常询问。具体以本项目 permissions.json 为准。用户可调整本地策略，不能在每次工具启动时重写回默认值。

## 条件动作的权限设计

当前权限计算读取根部 properties，不根据 oneOf 分支合并新的权限元数据。混合查询和写入动作时，要保证写入动作强制携带带写入权限的顶层字段；不能只在 oneOf 中写权限然后以为生效。

新建空白工具的例子：action 声明天策全局读取；create_category/create_tool 必须带 name，该字段声明天策全局写入；Schema 和执行器同时拒绝缺少 name 的写入动作。这样查看分类不会被当作写入，真正创建又不会绕过策略。

不能合理表达权限时拆分工具或扩展通用权限合同，不能隐瞒副作用。

## ask 的真实含义

平台先判定权限再执行 Python/client。ask 是否真的出现一次确认，还取决于会话的 tool_approval_mode；当前默认可为 auto_allow_ask。不要在说明里承诺“所有写入都会弹窗”。deny 应阻止执行。权限检查不是操作系统沙箱，Python 工具进程仍具有运行账户的系统访问能力，必须只使用可信工具并正确实现自身范围校验。

## 必须测试的边界

- 相对路径、绝对路径、工作区内外、符号链接与不存在路径。
- 写入与删除的覆盖策略、错误权限、拒绝时不发生动作。
- 非法参数在业务动作前失败；未知字段不会被悄悄忽略后执行别的动作。
- 超时、取消、断线发生在写入前、写入中、返回结果前的差异。
- 不因失败重试重复创建文件、项目、远端资源或重复提交付费任务。
- 部分完成返回已完成的身份/路径和后续处理方式；结果未知明确说未知。
- 日志、结果、案例、异常不包含密钥和会话凭据。

client 工具会复用平台原子领取与重放防重机制；这不等于所有业务都有事务或幂等键。当前创建项目 POST 若成功但响应丢失，不能假装没创建再自动重试。创建器会报告结果未知，要求先核对分类列表。
