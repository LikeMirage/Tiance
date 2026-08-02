from __future__ import annotations


def dynamic_tool_directory_intro_lines() -> list[str]:
    return [
        "【动态加载工具目录】",
        "",
        "以下是只提供了轻量摘要信息的动态加载工具，可以通过 load_tool_info 按需读取详细信息。",
        "如果需要调用某个动态工具，且本会话中尚未看到该工具的完整参数，先调用 load_tool_info，operation=get_parameters，读取其参数意义。",
        "执行动态工具时调用 execute_dynamic_tool：tool_name 填目标工具名，arguments 填目标工具的真实参数对象。",
        "如果本会话历史信息中已经读取过该工具的完整参数，可以直接调用 execute_dynamic_tool 执行。",
        "如需理解典型用法，可调用 load_tool_info，operation=get_examples，按需读取工具的应用示例。",
        "参数名只用于判断工具是否可能相关，禁止凭参数名猜测参数结构、默认值、可选值或必填规则。",
        "反例：凭借猜测直接执行未加载过完整参数的动态工具。",
    ]
