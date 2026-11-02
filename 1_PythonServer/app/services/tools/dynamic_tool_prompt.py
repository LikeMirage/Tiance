from __future__ import annotations

from app.domain.tools import ToolExampleDetail, ToolSummary


def dynamic_tool_directory_entry_lines(
    summary: ToolSummary,
    examples: tuple[ToolExampleDetail, ...] = (),
) -> list[str]:
    lines = [
        "",
        f"工具：{summary.name}",
        f"显示名称：{summary.display_name}",
        f"说明：{summary.description}",
    ]
    if summary.example_titles:
        lines.append("使用说明：")
        for index, title in enumerate(summary.example_titles, start=1):
            lines.append(f"{index}. {title}")
            if index <= len(examples):
                example = examples[index - 1]
                if example.inject_content and example.content:
                    lines.append(example.content)
    return lines


def dynamic_tool_directory_intro_lines() -> list[str]:
    return [
        "【动态加载工具目录】",
        "",
        "以下是只提供了轻量摘要信息的动态加载工具，可以通过 load_tool_info 按需读取详细信息。",
        "如果需要调用某个动态工具，且本会话中尚未看到该工具的完整参数，先调用 load_tool_info，operation=get_parameters，读取其参数意义。",
        "执行动态工具时调用 execute_dynamic_tool：tool_name 填目标工具名，arguments 填目标工具的真实参数对象。",
        "如果本会话历史信息中已经读取过该工具的完整参数，可以直接调用 execute_dynamic_tool 执行。",
        "操作流程、注意事项和调用示例通过 load_tool_info，operation=get_examples 按需读取，可按 example_titles 指定标题；使用前读取摘要要求的说明。",
        "轻量目录不包含参数结构、默认值、可选值或必填规则，禁止凭工具摘要猜测参数。",
        "反例：凭借猜测直接执行未加载过完整参数的动态工具。",
    ]
