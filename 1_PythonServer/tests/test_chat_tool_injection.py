import pytest

from app.domain.llm.chat import (
    ChatClientCapability,
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolDefinition,
)
from app.domain.tools import ToolExampleDetail, ToolParameterDetail, ToolSummary
from app.services.tools.chat_tool_injection import ChatToolInjectionService
from app.services.tools.tool_metadata import standard_tool_description


def test_chat_tool_injection_builds_all_catalog_tools_without_session_allowlist():
    service = ChatToolInjectionService(_FakeCatalog())

    tools = service.build_chat_tools(enabled_tool_names=None)

    assert [tool.name for tool in tools] == [
        "read_text_file",
        "inspect_workspace",
        "load_tool_info",
        "execute_dynamic_tool",
    ]
    assert tools[0].parameters["required"] == ["file_path"]
    assert tools[1].parameters["properties"]["mode"]["enum"] == ["summary", "tree", "find"]
    assert "permission_type" not in tools[1].parameters["properties"]["mode"]


def test_standard_tool_description_includes_example_titles_without_content_by_default():
    service = ChatToolInjectionService(_FakeCatalog())

    tools = service.build_chat_tools(enabled_tool_names=("read_text_file",))

    assert len(tools) == 1
    assert tools[0].description == (
        "读取本地纯文本文件。\n\n"
        "应用示例：\n"
        "1. 读取全文"
    )


def test_standard_tool_description_includes_only_explicitly_enabled_content():
    description = standard_tool_description(
        "执行工具。",
        (
            ToolExampleDetail(
                index=1,
                title="只显示标题",
                content="不应注入",
                inject_content=False,
            ),
            ToolExampleDetail(
                index=2,
                title="注入正文",
                content='{"mode":"full"}',
                inject_content=True,
            ),
        ),
    )

    assert description == (
        "执行工具。\n\n"
        "应用示例：\n"
        "1. 只显示标题\n"
        "2. 注入正文\n"
        '{"mode":"full"}'
    )


def test_chat_tool_injection_filters_by_session_enabled_names():
    service = ChatToolInjectionService(_FakeCatalog())

    tools = service.build_chat_tools(enabled_tool_names=("inspect_workspace", "parse_document"))

    assert [tool.name for tool in tools] == [
        "inspect_workspace",
        "load_tool_info",
        "execute_dynamic_tool",
    ]


def test_chat_tool_injection_empty_session_enabled_names_disables_all_tools():
    service = ChatToolInjectionService(_FakeCatalog())

    tools = service.build_chat_tools(enabled_tool_names=())

    assert tools == ()


def test_client_tools_are_injected_only_for_compatible_frontend_capabilities():
    service = ChatToolInjectionService(_FakeCatalog())

    without_capability = service.build_chat_tools(enabled_tool_names=None)
    with_old_capability = service.build_chat_tools(
        enabled_tool_names=None,
        client_capabilities=(ChatClientCapability(name="editor.tabs", version=1),),
    )
    with_supported_capability = service.build_chat_tools(
        enabled_tool_names=None,
        client_capabilities=(ChatClientCapability(name="editor.tabs", version=2),),
    )

    assert "editor_tabs_manager" not in [tool.name for tool in without_capability]
    assert "editor_tabs_manager" not in [tool.name for tool in with_old_capability]
    assert "editor_tabs_manager" in [tool.name for tool in with_supported_capability]


def test_chat_tool_injection_keeps_existing_request_tool_when_names_overlap():
    service = ChatToolInjectionService(_FakeCatalog())
    request = _request(
        tools=(
            ChatToolDefinition(
                name="read_text_file",
                description="已有定义",
                parameters={"type": "object", "properties": {"existing": {"type": "string"}}},
            ),
        )
    )

    injected = service.inject_request_tools(request, enabled_tool_names=None)

    assert [tool.name for tool in injected.tools] == [
        "read_text_file",
        "inspect_workspace",
        "load_tool_info",
        "execute_dynamic_tool",
    ]
    assert injected.tools[0].description == "已有定义"
    assert "existing" in injected.tools[0].parameters["properties"]


def test_chat_tool_injection_inserts_dynamic_tool_directory_for_dynamic_tools():
    service = ChatToolInjectionService(_FakeCatalog())

    injected = service.inject_request_tools(_request(), enabled_tool_names=("parse_document",))

    assert [tool.name for tool in injected.tools] == [
        "load_tool_info",
        "execute_dynamic_tool",
    ]
    assert injected.messages[0].role == ChatMessageRole.SYSTEM
    assert "【动态加载工具目录】" in injected.messages[0].content
    assert "轻量目录不包含参数结构" in injected.messages[0].content
    assert "load_tool_info，operation=get_parameters" in injected.messages[0].content
    assert "调用 execute_dynamic_tool" in injected.messages[0].content
    assert "arguments 填目标工具的真实参数对象" in injected.messages[0].content
    assert "直接调用目标工具名" not in injected.messages[0].content
    assert "operation=execute" not in injected.messages[0].content
    assert "工具：parse_document" in injected.messages[0].content
    assert "参数名：" not in injected.messages[0].content
    assert "1. 解析 PDF" in injected.messages[0].content


def test_dynamic_tool_directory_includes_only_explicitly_enabled_example_content():
    service = ChatToolInjectionService(_FakeCatalog())

    prompt = service.build_dynamic_tool_directory(enabled_tool_names=("parse_document",))

    assert "1. 解析 PDF" in prompt
    assert '{"file_path":"document.pdf"}' in prompt


def test_chat_tool_injection_keeps_dynamic_directory_after_existing_system_messages():
    service = ChatToolInjectionService(_FakeCatalog())
    request = _request(
        messages=(
            ChatMessage(role=ChatMessageRole.SYSTEM, content="已有系统提示"),
            ChatMessage(role=ChatMessageRole.USER, content="hi"),
        )
    )

    injected = service.inject_request_tools(request, enabled_tool_names=("parse_document",))

    assert [message.role for message in injected.messages[:2]] == [
        ChatMessageRole.SYSTEM,
        ChatMessageRole.SYSTEM,
    ]
    assert injected.messages[0].content == "已有系统提示"
    assert injected.messages[1].content.startswith("【动态加载工具目录】")


def test_chat_tool_injection_filters_dynamic_directory_by_session_enabled_names():
    service = ChatToolInjectionService(_FakeCatalog())

    prompt = service.build_dynamic_tool_directory(enabled_tool_names=("read_text_file",))

    assert prompt == ""


def test_chat_tool_injection_raises_when_parameters_cannot_be_loaded():
    service = ChatToolInjectionService(_FakeCatalog(broken_tool_names={"inspect_workspace"}))

    with pytest.raises(RuntimeError, match="broken schema"):
        service.build_chat_tools(enabled_tool_names=None)


def _request(
    *,
    tools: tuple[ChatToolDefinition, ...] = (),
    messages: tuple[ChatMessage, ...] | None = None,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4",
        messages=messages or (ChatMessage(role=ChatMessageRole.USER, content="hi"),),
        project_id="project-1",
        session_id="session-1",
        tools=tools,
    )


class _FakeCatalog:
    def __init__(self, *, broken_tool_names: set[str] | None = None) -> None:
        self._broken_tool_names = broken_tool_names or set()

    def list_tool_summaries(self):
        return (
            ToolSummary(
                name="read_text_file",
                display_name="文本读取",
                description="读取本地纯文本文件。",
                keywords=("文本",),
                category="基础工具",
                dynamic=False,
                parameter_names=("file_path",),
                example_titles=(),
            ),
            ToolSummary(
                name="inspect_workspace",
                display_name="工作区信息查看",
                description="查看工作区路径和文件树。",
                keywords=("工作区",),
                category="基础工具",
                dynamic=False,
                parameter_names=("mode",),
                example_titles=(),
            ),
            ToolSummary(
                name="load_tool_info",
                display_name="工具信息加载",
                description="读取动态工具参数和示例。",
                keywords=("工具参数",),
                category="基础工具",
                dynamic=False,
                parameter_names=("operation", "tool_name"),
                example_titles=("读取参数",),
            ),
            ToolSummary(
                name="execute_dynamic_tool",
                display_name="动态工具执行",
                description="执行已启用的动态加载工具。",
                keywords=("动态工具",),
                category="基础工具",
                dynamic=False,
                parameter_names=("tool_name", "arguments"),
                example_titles=("切换主题",),
            ),
            ToolSummary(
                name="parse_document",
                display_name="文档解析",
                description="将 PDF 或图片解析为 Markdown。",
                keywords=("文档",),
                category="基础工具",
                dynamic=True,
                parameter_names=("file_path",),
                example_titles=("解析 PDF",),
            ),
            ToolSummary(
                name="editor_tabs_manager",
                display_name="编辑器标签",
                description="管理编辑器标签。",
                keywords=("编辑器",),
                category="基础工具",
                dynamic=False,
                parameter_names=("action",),
                example_titles=(),
                client_capability_name="editor.tabs",
                client_capability_min_version=2,
            ),
        )

    def get_tool_parameters(self, tool_name: str):
        if tool_name in self._broken_tool_names:
            raise RuntimeError("broken schema")
        if tool_name == "inspect_workspace":
            return ToolParameterDetail(
                name=tool_name,
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["summary", "tree", "find"],
                            "permission_type": "filesystem_read",
                        },
                    },
                },
            )
        if tool_name == "execute_dynamic_tool":
            return ToolParameterDetail(
                name=tool_name,
                input_schema={
                    "type": "object",
                    "required": ["tool_name", "arguments"],
                    "properties": {
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                },
            )
        if tool_name == "load_tool_info":
            return ToolParameterDetail(
                name=tool_name,
                input_schema={
                    "type": "object",
                    "required": ["operation", "tool_name"],
                    "properties": {
                        "operation": {"type": "string"},
                        "tool_name": {"type": "string"},
                    },
                },
            )
        if tool_name == "editor_tabs_manager":
            return ToolParameterDetail(
                name=tool_name,
                input_schema={
                    "type": "object",
                    "required": ["action"],
                    "properties": {"action": {"type": "string"}},
                },
            )
        return ToolParameterDetail(
            name=tool_name,
            input_schema={
                "type": "object",
                "required": ["file_path"],
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径。",
                    },
                },
            },
        )

    def get_tool_examples(self, tool_name: str, *, include_all: bool = False):
        assert include_all is True
        if tool_name == "read_text_file":
            return (
                ToolExampleDetail(
                    index=1,
                    title="读取全文",
                    content='{"file_path":"notes.md"}',
                ),
            )
        if tool_name == "parse_document":
            return (
                ToolExampleDetail(
                    index=1,
                    title="解析 PDF",
                    content='{"file_path":"document.pdf"}',
                    inject_content=True,
                ),
            )
        return ()
