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

## 生成地址、模型发现与历史思考

生成请求和模型发现分别保存地址。修改生成地址时，仍处于自动关联状态的模型发现地址会按协议和预置地址关系重新推导；用户已改为独立地址时继续使用其填写值。这可以覆盖生成端点和 `/models` 路径不同的服务。[地址推导](../2_ReactWeb/src/features/provider-config/model/deriveProviderModelDiscoveryUrl.ts) · [配置更新](../2_ReactWeb/src/features/provider-config/model/providerConfigDraftRules.ts)

供应商的 `reasoning_replay_mode` 决定下一次请求携带哪些历史助手思考，默认值为 `tool_call_rounds`。`never` 关闭历史思考回放，`tool_call_rounds` 仅用于带工具调用的助手消息，`always` 允许所有助手消息回放。每轮回复使用哪个思考档位仍由会话的生成设置决定。[回放枚举](../1_PythonServer/app/domain/llm/reasoning_replay.py) · [回放选择](../1_PythonServer/app/infra/llm/chat_adapters/reasoning_replay.py)

四类协议分别处理可回放的思考文字或续传内容。Responses 的 reasoning item、Anthropic 的 thinking/redacted block、Gemini 的 thought/signature 还须匹配原协议、供应商和模型身份。切换来源后重新组装公共历史，已保存的思考仍能供用户查阅。[协议续传合同](01_LLM协议适配结构.md#第一层协议适配器) · [适配回归](../1_PythonServer/tests/test_reasoning_replay_policy.py)

## 请求验证

生成参数通过统一 `generation` 对象进入领域请求。模型能力、输出格式、思考模式、采样参数、最大输出和工具支持在出站前验证。未知字段和无效枚举应在保存或请求边界明确失败，而不是由底层解析器替换成默认值。

重试次数、工具调用上限和畸形工具调用恢复都属于可观察运行策略。它们不能在前端、Schema、领域对象、仓储和执行层分别复制默认值。

## 流式终态和重试

流结束必须由协议终态证明，而不是只看连接 EOF。提前中断形成 `upstream_stream_incomplete`；流式重试通过 `retry_reset` 撤销尚未提交的当前尝试片段，已经提交的正式工具轮次继续保留。

用户取消不应重试。审计尝试记录与正式助手消息分开保存。

## 协议续传状态

Responses reasoning item、Anthropic thinking signature 和 Gemini thought signature 用于继续同一供应商工具轮。当前公共消息领域仍保存带种类的续传载荷；后续扩展时应避免让通用领域枚举持续理解每个新供应商的私有结构。

## 供应商内置网络搜索

工具包按调用会话的生成地址选择包内端点，独立决定搜索协议。主会话使用 Chat Completions 时，搜索可使用同源的 Responses 接口。后端通过 `session_model` 提供模型来源，绑定同一供应商、模型和凭据。

当前会话的原生搜索适配 OpenAI Responses、Anthropic 和 Gemini。另有独立的 `deepseek_official_web_search` 工具，使用 DeepSeek 搜索和网页读取服务，凭据来源与当前对话模型分开。见[供应商能力桥与内置网络搜索](10_后端供应商能力桥与内置网络搜索.md#deepseek-独立搜索与网页读取)。

## 实现索引

- 协议适配器：`1_PythonServer/app/infra/llm/chat_adapters/`
- Provider Profile：`1_PythonServer/app/infra/llm/provider_profiles/`
- 声明规则：`1_PythonServer/app/domain/llm/provider_adaptation.py`
- 规则仓库：`1_PythonServer/app/repositories/llm/provider_adaptation_rules_repository.py`
- 请求校验：`1_PythonServer/app/services/llm/chat/request_validation.py`
- 供应商配置 API：`1_PythonServer/app/api/routes/llm/provider_configs.py`
- host capability：`1_PythonServer/app/services/tools/host_capability_access.py`
