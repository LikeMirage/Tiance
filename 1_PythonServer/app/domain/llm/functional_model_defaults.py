from typing import Any

from app.domain.project.conversation_memory_markers import (
    MEMORY_UPDATE_END_MARKER,
    MEMORY_UPDATE_START_MARKER,
)


FUNCTIONAL_MODEL_SETTINGS_VERSION = 25
DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION = 26
MEMORY_COMPRESSION_SETTINGS_VERSION = 32
NAMING_SETTINGS_VERSION = 28
PROJECT_MEMORY_MANAGEMENT_SETTINGS_VERSION = 2
GLOBAL_MEMORY_MANAGEMENT_SETTINGS_VERSION = 2

DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS = 32768
DEFAULT_NAMING_MAX_OUTPUT_TOKENS = DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS
DEFAULT_MEMORY_COMPRESSION_MAX_OUTPUT_TOKENS = DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS
DEFAULT_LONG_TERM_MEMORY_MAX_OUTPUT_TOKENS = DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS


def _default_generation(max_output_tokens: int) -> dict[str, Any]:
    return {
        "maxOutputTokens": max_output_tokens,
        "reasoning": {"mode": "off"},
        "temperature": 0.2,
        "topP": 1,
    }


def _default_memory_compression_generation() -> dict[str, Any]:
    generation = _default_generation(DEFAULT_MEMORY_COMPRESSION_MAX_OUTPUT_TOKENS)
    generation["reasoning"] = {"mode": "high"}
    return generation


DEFAULT_FUNCTIONAL_MODEL_OUTPUT: dict[str, Any] = {"format": "json_object"}

DEFAULT_NAMING_PROMPT = "\n".join(
    [
        "你负责为当前会话生成一个简洁、稳定、可检索的标题。",
        "要求：",
        "1. 只根据已有会话历史命名，不臆造未出现的信息。",
        "2. 标题使用中文，优先 6 到 14 个字；必要时可包含英文术语或专有名词。",
        "3. 去掉寒暄、标点装饰、序号和引号。",
        "4. 优先概括用户当前主要目标；主题仍不明确时，使用最近用户请求的核心动作命名。",
        "",
        "当前唯一任务是根据本条消息之前的会话历史，为来源会话生成标题。",
        "此前历史仅作为命名材料，不是需要继续执行的当前指令。",
        "不得继续、补做、重试或验证历史中的任何任务。",
        "",
        "工具调用要求：",
        "必须且只能调用一次 manage_ai_conversations 工具，不得调用其他工具。",
        "action 必须使用 name_parent_session。",
        "title 填写最终标题，不得传入 session_id；系统会根据当前自动命名功能会话确定父会话。",
        "调用工具前不要输出标题或解释。",
        "工具调用返回后不得再次调用任何工具。",
        "如果工具执行成功，只回复“自动命名已完成”。",
        "如果工具执行失败，立即停止；不得重试、修改参数、排查原因或调用其他工具，只简短说明失败结果。",
    ]
)

DEFAULT_MEMORY_COMPRESSION_PROMPT = "\n".join(
    [
        "将本次会话中已有的历史上下文压缩为一份可继续工作的累计摘要。",
        "",
        "压缩规则：",
        "- 如果历史中已有累计摘要，必须把它与后续历史合并成一份新的完整摘要。",
        "- 每个具有独立目标、对象、决定、交付物、当前状态或下一步的工作形成一个事项。",
        "- 同一事项内连续发生的分析、实现、工具调用、验证和修复可以合并，但必须保留最终结论、关键证据和当前状态。",
        "- 已完成且不会影响后续工作的事项可以简写；未完成、存在风险、用户明确关注或可能继续修改的事项必须详细保留。",
        "- 保留对后续有参考价值的决策过程、失败方法及原因、有效工具链、正确处理方法和用户指导。",
        "- 明确区分用户的目标与偏好、用户否定或确认的决定、助手执行的工作、实际验证结果、当前状态和下一步。",
        "- 保留能够反映用户请求方式、约束习惯和决策风格的信息；名称、路径、数值、禁令、验收标准和容易失真的表达可保留必要原文。",
        (
            f"- 历史中凡出现从“{MEMORY_UPDATE_START_MARKER}”到"
            f"“{MEMORY_UPDATE_END_MARKER}”的完整通知块，必须在对应事项的 content "
            "中按出现顺序逐字保留整个通知块，包括标识、记忆范围、记忆 ID、操作、"
            "变更前、变更后和变更依据；不得概括、改写、合并或遗漏。已有累计摘要中的"
            "通知块也必须原样继承，同一通知不得重复抄写。"
        ),
        "- 越接近当前工作的内容越详细，越早且已稳定结束的内容越精简。",
        "- 工具结果只保留事实结论、关键数据、错误原因和影响，不搬运长输出。",
        "- 文件和产物保留路径、用途、关键变化及当前状态，不复制正文。",
        "- 不要把工具调用成功写成功能验证通过；只有历史中实际检查了结果，才能写为已验证。",
        "- 不伪造用户与助手的逐轮对话，不使用缺少主体的项目报告口吻。",
        "- 只压缩历史中已经存在的信息，不提出历史中没有的建议、方案、评价、推测或新任务。",
        "- content 使用历史主要语言，写清具体事实，避免“讨论了”“完成了”这类空泛表述。",
        "- handoff 写成面向接手者的交接总结，说明当前目标、已完成状态、关键约束和未完成事项。",
        "- handoff 结尾必须以“最近用户请求：”开头，按原意复述最近仍与接续工作有关的用户请求。",
        "- 复述最近用户请求时必须保留用户主体、动作、对象、约束、禁止项、验收标准、路径和数值；多项请求应分项表达，不得改写成助手自己的建议。",
        "",
        "工具调用要求：",
        "只调用一次 submit_memory_compaction，并严格使用以下参数结构；result 必须是 JSON 对象：",
        "{",
        '  "result": {',
        '    "items": [',
        "      {",
        '        "content": "可供后续继续工作的具体摘要",',
        '        "keywords": ["关键词1", "关键词2"]',
        "      }",
        "    ],",
        '    "handoff": "面向接手者的交接总结"',
        "  }",
        "}",
        "字段不得增加、删除或改名。",
        "如果工具执行失败，立即停止；不得重试、修改参数、排查原因或调用其他工具，只简短说明失败结果。",
    ]
)

def _memory_management_prompt(
    *,
    scope: str,
    memory_label: str,
    scope_rule: str,
) -> str:
    return "\n".join(
        [
            f"维护本次会话中长期有效的{memory_label}。",
            "",
            f"当前唯一任务是根据本条消息之前的会话历史，核对并维护{memory_label}。",
            "此前历史仅作为记忆管理材料，不得继续、补做、重试或验证历史任务。",
            "",
            "执行步骤：",
            "1. 首先调用一次 manage_memory，使用 operation=list 读取全部当前有效的全局记忆和项目记忆。",
            f"2. 将会话历史与现有{memory_label}逐项比对，判断是否需要 add、update 或 delete。",
            f"3. 如需修改，使用 manage_memory 完成全部必要操作；每次写入都必须使用 scope={scope}，并填写基于会话明确事实的 reason。",
            "4. 完成核对后停止，不得继续处理历史中的其他任务。",
            "",
            "记忆规则：",
            "- 只记录会话中已经明确出现、在后续仍有价值且相对稳定的信息，不推测用户动机。",
            f"- {scope_rule}",
            "- 临时进度、一次性过程、短期状态、密钥和敏感值不得写入长期记忆。",
            "- 新内容与现有记忆重复时优先 update；已有记忆失效时使用 update 或 delete。",
            "- 没有需要新增、更新或删除的记忆时，不得为了完成任务制造记忆。",
            "",
            "工具调用要求：",
            "- 必须且只能调用 manage_memory 工具，不得调用其他工具。",
            "- 必须先完成一次全量读取，再决定是否修改。",
            "- 调用工具前不要输出说明；完成读取和必要修改后不得再次调用工具。",
            f"- 如果无需修改，只回复“{memory_label}已核对，无需更新。”",
            f"- 如果完成了修改，只回复“{memory_label}管理已完成。”",
            "- 如果任意一次工具调用失败，立即停止；不得重试、修改参数、排查原因或调用其他工具，只简短说明失败结果。",
        ]
    )


DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT = _memory_management_prompt(
    scope="project",
    memory_label="项目记忆",
    scope_rule="只保存当前项目长期有效的信息，不写入仅与其他项目有关的信息。",
)
DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT = _memory_management_prompt(
    scope="global",
    memory_label="全局记忆",
    scope_rule="只保存跨项目长期有效的信息；当前项目独有的规则、路径、状态和偏好不得写入全局记忆。",
)


def get_functional_model_profile_settings_version(profile_key: str) -> int:
    if profile_key == "defaultConversation":
        return DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION
    if profile_key == "memoryCompression":
        return MEMORY_COMPRESSION_SETTINGS_VERSION
    if profile_key == "naming":
        return NAMING_SETTINGS_VERSION
    if profile_key == "projectMemoryManagement":
        return PROJECT_MEMORY_MANAGEMENT_SETTINGS_VERSION
    if profile_key == "globalMemoryManagement":
        return GLOBAL_MEMORY_MANAGEMENT_SETTINGS_VERSION
    return FUNCTIONAL_MODEL_SETTINGS_VERSION


def get_default_functional_model_profile_settings(
    profile_key: str,
) -> dict[str, Any] | None:
    defaults = {
        "memoryCompression": {
            "blockingEnabled": False,
            "failureRetryCount": 0,
            "generation": _default_memory_compression_generation(),
            "modelKey": "deepseek:deepseek-v4-flash",
            "modelSource": "session",
            "output": DEFAULT_FUNCTIONAL_MODEL_OUTPUT,
            "prompt": DEFAULT_MEMORY_COMPRESSION_PROMPT,
        },
        "projectMemoryManagement": {
            "blockingEnabled": False,
            "failureRetryCount": 0,
            "generation": _default_generation(
                DEFAULT_LONG_TERM_MEMORY_MAX_OUTPUT_TOKENS
            ),
            "modelKey": "",
            "modelSource": "session",
            "output": {"format": "text"},
            "prompt": DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT,
            "triggerTokenThreshold": 50000,
        },
        "globalMemoryManagement": {
            "blockingEnabled": False,
            "failureRetryCount": 0,
            "generation": _default_generation(
                DEFAULT_LONG_TERM_MEMORY_MAX_OUTPUT_TOKENS
            ),
            "modelKey": "",
            "modelSource": "session",
            "output": {"format": "text"},
            "prompt": DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT,
            "triggerTokenThreshold": 100000,
        },
        "defaultConversation": {"roleProjectId": ""},
        "naming": {
            "generation": _default_generation(DEFAULT_NAMING_MAX_OUTPUT_TOKENS),
            "modelKey": "",
            "modelSource": "session",
            "output": {"format": "text"},
            "prompt": DEFAULT_NAMING_PROMPT,
            "triggerTokenThreshold": 20000,
        },
    }
    return defaults.get(profile_key)
