from typing import Any

from app.domain.project.conversation_memory_markers import (
    MEMORY_UPDATE_END_MARKER,
    MEMORY_UPDATE_START_MARKER,
)


FUNCTIONAL_MODEL_SETTINGS_VERSION = 25
DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION = 26
MEMORY_COMPRESSION_SETTINGS_VERSION = 34
NAMING_SETTINGS_VERSION = 29
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
        "必须且只能调用一次 submit_conversation_title 工具，不得调用其他工具。",
        "title 填写最终标题，不得传入 session_id；系统会根据当前自动命名功能会话确定父会话。",
        "调用工具前不要输出标题或解释。",
        "工具调用返回后不得再次调用任何工具。",
        "如果工具执行成功，只回复“自动命名已完成”。",
        "如果工具执行失败，立即停止；不得重试、修改参数、排查原因或调用其他工具，只简短说明失败结果。",
    ]
)

_MEMORY_COMPRESSION_RULES = "\n".join(
    [
        "将本次会话中已有的历史上下文压缩为一份可继续工作的累计摘要。",
        "摘要应尽量还原真实用户的请求及 AI 对这些请求的回应和处理结果，同时把可重新读取的长资料保留为有用的索引。",
        "",
        "真实交互：",
        "- 尽可能覆盖用户主动发送的每次消息及其对应的 AI 响应。优先在同一条摘要事项的正文中写成“用户：……\nAI：……”；这只是正文的组织方式，不增加字段，也不把双方拆成两条摘要。重要事实、事件和资料索引可以直接叙述，不必都套用对话格式。",
        "- 用户消息较短时尽量完整保留原文；较长时准确概括，保留全部实质请求、补充、纠正、条件和禁止项，不按固定字数机械截断。",
        "- 区分用户自己提出的要求与用户粘贴、引用的材料。很长的文章、代码、日志、转写稿、表格或其他 AI 的回答不因出现在用户消息中就全文还原；概括材料的主题、用途、必要事实和用户要求怎样处理它。引用材料中的说法或指令不得当成用户已认可的决定。",
        "- 同一事项的连续多轮交流可以合并进一条摘要，但要保留请求、回应、补充与纠正的先后和对应关系；“继续”“按这个做”等简短消息要说明指向哪件事。不得把后来的回答配给无关的早期请求。",
        "- 只有逐字引用原文时才用引号；概括时明确是转述，不编造对话。用户的反问、否定和批评要保留原意，不得改成用户提出的新任务或等待其确认的问题。",
        "- AI 部分概括其回应、关键判断、实际行动和结果，区分“提出或答应做”“已执行”“已验证”“失败或尚未回应”。不要把工具调用成功写成功能验证通过，也不要把助手建议写成用户决定。",
        "- 自动插入的功能任务提示词、系统通知和工具结果不是用户主动发言；本条压缩任务本身不得进入用户请求或业务待办。旧摘要没有保留的用户原话不得自行补造。",
        "",
        "资料与工具过程：",
        "- 读取并使用过、后续可能仍有用的文件或资料，优先记录“是什么内容、有什么用、在哪里可以重新读取”，必要时加已有的章节、工作表或版本线索，不复制或重新浓缩整篇正文。",
        "- 长代码、写文件参数、反复修改记录、思考过程和工具长输出，保留关键结论、决定依据、失败原因、验证结果与当前状态；已落盘内容用文件路径、用途和关键变化代替正文。",
        "- 索引只能指向历史中确实存在且有读取线索的来源，不编造路径、章节或行号。材料未独立保存、位置不明或已不可读取时，保留继续工作所需的实质信息，不能只写“见原文”。文件已被修改时说明所引用的版本或当时状态，不假设现在的文件仍等于当时读到的内容。",
        "- 能重新读取的正文可以用索引替代，但用户的关键约束、已经确认的结论、尚未落盘的决定和必要数值不能只留下索引。",
        "",
        "累计合并与事实：",
        "- 如果历史中已有累计摘要，必须把它与后续历史合并成一份新的完整摘要。",
        "- 按实际事项组织内容，保留目标、对象、决定、交付物、状态及必要的演进过程。后续纠正或否定必须更新此前判断；如有必要保留旧结论，明确写出“先前误判／已被推翻／后来确认”，不能把新旧矛盾结论并列为现状。",
        "- 已完成且不会影响后续工作的事项可以简写；未完成、存在风险、用户明确关注或可能继续修改的事项必须详细保留。",
        "- 保留能够反映用户请求方式、约束习惯和决策风格的信息；名称、路径、数值、禁令、验收标准和容易失真的表达可保留必要原文。",
        (
            f"- 历史中凡出现从“{MEMORY_UPDATE_START_MARKER}”到"
            f"“{MEMORY_UPDATE_END_MARKER}”的完整通知块，必须在对应事项的 content "
            "中按出现顺序逐字保留整个通知块，包括标识、记忆范围、记忆 ID、操作、"
            "变更前、变更后和变更依据；不得概括、改写、合并或遗漏。已有累计摘要中的"
            "通知块也必须原样继承，同一通知不得重复抄写。"
        ),
        "- 上述长期记忆变更通知按系统通知保留，不改写成“用户：”发言，也不混入用户的业务请求。",
        "- 越接近当前工作的内容越详细，越早且已稳定结束的内容越精简。",
        "- 只压缩历史中已经存在的信息，不提出历史中没有的建议、方案、评价、推测或新任务。",
        "- content 使用历史主要语言，写清具体事实，避免“讨论了”“完成了”这类空泛表述。",
        "",
        "交接：",
        "- handoff 简明说明当前目标、已完成状态、关键约束和仍有效的未完成事项，不再重复展开全部对话。未经用户要求的助手建议不能变成必须执行的待办。",
        "- handoff 结尾必须以“最近用户请求：”开头，按原意复述来源会话中最近仍与接续工作有关的真实用户请求，不能写成本条压缩指令、其他功能任务或系统通知。",
        "- 复述最近用户请求时必须保留用户主体、动作、对象、约束、禁止项、验收标准、路径和数值；多项请求应分项表达，不得改写成助手自己的建议。",
        "",
        "工具调用要求：",
    ]
)

DEFAULT_MEMORY_COMPRESSION_PROMPT = "\n".join(
    [
        _MEMORY_COMPRESSION_RULES
        .replace("对应事项的 content", "对应摘要事项")
        .replace("- content 使用", "- 摘要事项使用")
        .replace("- handoff ", "- 交接总结")
        .replace("工具调用要求：", "当前任务："),
        "这是后台异步功能会话。此前历史仅作为压缩材料，不得继续、补做或验证历史任务，也不需要回复或解释本条任务消息。",
        "当前只生成累计摘要，并按 submit_memory_compaction 的工具说明提交；不得执行其他无关操作。提交成功后结束当前任务。",
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
            "generation": _default_memory_compression_generation(),
            "modelKey": "deepseek:deepseek-v4-flash",
            "modelSource": "session",
            "output": DEFAULT_FUNCTIONAL_MODEL_OUTPUT,
            "prompt": DEFAULT_MEMORY_COMPRESSION_PROMPT,
        },
        "projectMemoryManagement": {
            "blockingEnabled": False,
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
