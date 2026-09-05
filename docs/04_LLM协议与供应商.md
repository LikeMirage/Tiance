# LLM 协议与供应商

## 分层

天策当前支持的主要协议族包括 OpenAI Chat Completions 兼容协议、OpenAI Responses、Anthropic Messages 和 Gemini GenerateContent。

差异分为三层：

1. 协议适配器负责请求、响应和流事件形状。
2. Provider Profile 负责少量必须由代码完成的供应商结构变化。
3. `provider-rules.json` 与 `model-rules.json` 负责声明式能力和字段规则。

通用聊天流程只消费统一消息、工具调用、用量和错误合同。新增供应商差异优先进入对应适配层，不能按供应商名称在通用会话 service 中增加分支。

## 供应商项目

供应商目录可包含：

```text
manifest.json
provider.json
credentials.json
models.json
cloud-model-cache.json
provider-rules.json
model-rules.json
```

市场包不得包含 `credentials.json`。已有供应商更新应保护 API 地址、认证、密钥、模型和本地分类；声明规则更新不能暗中重置用户配置。

## 请求验证

生成参数通过统一 `generation` 对象进入领域请求。模型能力、输出格式、思考模式、采样参数、最大输出和工具支持在出站前验证。未知字段和无效枚举应在保存或请求边界明确失败，而不是由底层解析器替换成默认值。

重试次数、工具调用上限和畸形工具调用恢复都属于可观察运行策略。它们不能在前端、Schema、领域对象、仓储和执行层分别复制默认值。

## 流式终态和重试

流结束必须由协议终态证明，而不是只看连接 EOF。提前中断形成 `upstream_stream_incomplete`；流式重试通过 `retry_reset` 撤销尚未提交的当前尝试片段，已经提交的正式工具轮次继续保留。

用户取消不应重试。审计尝试记录与正式助手消息分开保存。

## 协议续传状态

Responses reasoning item、Anthropic thinking signature 和 Gemini thought signature 用于继续同一供应商工具轮。当前公共消息领域仍保存带种类的续传载荷；后续扩展时应避免让通用领域枚举持续理解每个新供应商的私有结构。

## 供应商内置网络搜索

普通 Python 工具通过后端 host capability 使用当前会话供应商的原生搜索。后端签发绑定调用、项目、会话、供应商和模型的短期凭据；工具不直接读取 API Key。

目前适配 OpenAI Responses、Anthropic 和 Gemini 的内置搜索。它不是任意 HTTP 代理。

## 实现索引

- 协议适配器：`1_PythonServer/app/infra/llm/chat_adapters/`
- Provider Profile：`1_PythonServer/app/infra/llm/provider_profiles/`
- 声明规则：`1_PythonServer/app/domain/llm/provider_adaptation.py`
- 规则仓库：`1_PythonServer/app/repositories/llm/provider_adaptation_rules_repository.py`
- 请求校验：`1_PythonServer/app/services/llm/chat/request_validation.py`
- 供应商配置 API：`1_PythonServer/app/api/routes/llm/provider_configs.py`
- host capability：`1_PythonServer/app/services/tools/host_capability_access.py`
