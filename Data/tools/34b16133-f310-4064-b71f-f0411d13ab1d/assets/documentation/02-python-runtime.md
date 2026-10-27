# 02 Python 运行、配置、依赖与资源

## 标准入口

平台将一次调用参数作为 JSON 对象写入独立 Python 子进程的标准输入，读取标准输出的一个最终 JSON 对象。优先复用应用源码 `1_PythonServer/tiance_runtime.py`：

```python
from tiance_runtime import run_tool

def run(payload):
    # 校验、处理真实业务；示例仅展示返回结构。
    return {"ok": True, "summary": "处理完成", "data": {"count": 1}}

if __name__ == "__main__":
    run_tool(run)
```

`run_tool` 读取对象、把处理函数中的 stdout 日志重定向到 stderr、检查返回值能否 JSON 序列化、捕获异常并输出失败对象。失败返回非零退出码。不要在调用 run_tool 前输出日志，也不要把密钥或全部环境变量放入异常。需要清楚的业务错误时自己返回结构化失败。

本模板的入口不执行任何业务，正常返回未实现错误。完成后应替换 run，并同步 Schema、案例和测试。不要简单改 ok=true 使体检“通过”。

## 三种路径不要混淆

- `Path(__file__).resolve().parent`：入口所在 program，可定位工具自己的 config.json、模块和模板。
- 入口目录的父目录：工具项目根，可定位 assets、.tool 和 docs。
- `TIANCE_WORKSPACE_ROOT`：调用方的工作区，通常也是进程 cwd；用于用户输入和产物。

后端无有效调用工作区时可能退回工具根作为 cwd，不能把 cwd 当作永远的用户项目。需要工作区的工具应检查环境值并明确报错。访问范围与符号链接解析、覆盖规则必须由程序落实，不要默默把工作区外路径改成另一个文件。

## 环境与模型上下文

| 环境项 | 含义 |
| --- | --- |
| `TIANCE_WORKSPACE_ROOT` | 调用工作区绝对路径（有上下文时） |
| `TIANCE_TOOLS_ROOT` | 本机工具集目录 |
| `TIANCE_PROJECT_ID` / `TIANCE_SESSION_ID` | 调用方的项目与会话；不是工具自己的项目 ID |
| `TIANCE_MODEL_CONTEXT` | JSON，provider_id、model_id、input_modalities |
| `TIANCE_API_BASE_URL` | 后端 API 基址，已包含 /api；它不是认证凭据 |
| `TIANCE_HOST_CAPABILITY_TOKEN` | 只有被授权的工具才会获得的短期能力凭据 |

读取模型能力可用 `get_model_context()`、`model_supports_input("image")`。不要只凭模型名称猜视觉能力，更不要为此读供应商数据库。宿主凭据禁止打印、落盘或转交其他进程。

启动器保留白名单中的常用 Windows 路径变量（SystemDrive、SystemRoot、WINDIR、用户目录等），其余环境不保证存在；实际清单见 `tool_execution_runtime.py`。需要密钥或服务地址时在工具自己的配置中明确声明，不能假定宿主的全部环境会透传。

## 业务配置和依赖

`program/config.json` 是工具自己的业务配置，空模板为 `{}`。有密钥的工具可提供明确的 configure 动作，修改本工具配置并只返回配置状态，不能把完整密钥回显。配置写入使用临时文件原子替换；校验字段、清除行为与权限；发布模板中的密钥必须为空。不要无条件吞掉配置解析错误并用猜测值继续请求外部服务。

第三方库列入 `program/requirements.txt`，注明或固定已验证版本。平台依赖管理会安装到本工具 dependencies 下的 py313 环境；可能通过 active.json 指向版本化目录，不要自己覆盖它。`tiance_runtime` 是宿主提供的帮助模块，不是需要 pip 安装的第三方包。

解释器优先使用应用 `runtime/python/py313/python.exe`。启动时路径包含入口目录、工具私有 site-packages、后端共享依赖、后端源码根。正常工具不要因为能 import app 就直接调用内部数据库和服务：子进程不是主后端，缓存、锁、认证和生命周期都可能不一致。

## 返回文本、文件和图片

短结果直接返回。大结果保存到调用方工作区，返回文件绝对路径、字节数、字符数和有明确长度的摘要；说明正文是否完整保存、预览是否截断。不能只返回裁剪片段却声称返回了完整正文。二进制文件返回大小、类型和路径即可。

要让视觉模型看到图片，返回标准内容块：

```json
{
  "ok": true,
  "summary": "已生成预览",
  "content": [
    {"type": "resource_link", "uri": "tiance-project:///images/preview.png", "name": "preview.png", "mimeType": "image/png"}
  ]
}
```

tiance-project 的路径相对调用工作区，不能指向工具 assets 却当作调用工作区文件。外部本地图片使用受控的 tiance-local URI，编码及限制应复用 `tool_resource_uris.py` 中的合同。后端还会检查本地文件、真实格式、资源范围和模型输入模态；写一个资源链接不会绕过这些检查。不要把大 Base64 塞进普通文本。

## 超时、并发与进程

runtime.timeout_seconds 是工具总执行预算。工具内部网络请求、子进程和重试应在预算内，不能悄悄把用户给定的业务时长缩短后仍宣称完成。平台取消 Python 工具会终止前台进程树，不能据此保证已经写出的文件或远端操作自动回滚。

并发关闭影响调度，不保证不同会话或手动运行永不同时访问资源。覆盖文件、维护共享缓存或使用常驻进程时仍要有资源级互斥、身份验证和幂等处理。只有业务确实需要时才设计后台进程，必须提供可追踪的状态、关闭和异常回收方式。
