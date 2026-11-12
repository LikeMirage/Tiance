"""Public host capability contract shared by tool config, SDK and gateway.

This registry describes capabilities, never individual tool names. Routes still
authenticate every request; registering a path does not implement its handler.
"""
from dataclasses import dataclass
from enum import StrEnum


class HostCapability(StrEnum):
    WEB_SEARCH = "web_search"
    DEEPSEEK_WEB = "deepseek_web"
    GITHUB_SYNC = "github_sync"
    GIT_REPOSITORY = "git_repository"
    GITHUB_REPOSITORIES = "github_repositories"
    GITHUB_PULL_REQUESTS = "github_pull_requests"
    GITHUB_ISSUES = "github_issues"
    GITHUB_RELEASES = "github_releases"
    GITHUB_ACTIONS = "github_actions"
    MEMORY_MANAGEMENT = "memory_management"
    TOOL_CATALOG = "tool_catalog"
    RUN_STATUS = "run_status"
    CONVERSATION_NAMING = "conversation_naming"
    EXTERNAL_MESSAGING = "external_messaging"


@dataclass(frozen=True, slots=True)
class HostCapabilityDefinition:
    path: str
    description: str


HOST_CAPABILITIES = {
    HostCapability.EXTERNAL_MESSAGING: HostCapabilityDefinition("/tools/capabilities/external-messaging", "列出接入连接，并通过已配置机器人向明确指定的聊天单向发送文字或文件"),
    HostCapability.CONVERSATION_NAMING: HostCapabilityDefinition("/tools/capabilities/conversation-naming", "自动命名功能会话向自己的来源会话提交标题"),
    HostCapability.WEB_SEARCH: HostCapabilityDefinition("/llm/provider-capabilities/web-search", "使用当前供应商和模型执行内置搜索"),
    HostCapability.DEEPSEEK_WEB: HostCapabilityDefinition("/llm/provider-capabilities/deepseek-web", "复用模型集 DeepSeek 凭据执行 Search/Fetch"),
    HostCapability.GITHUB_SYNC: HostCapabilityDefinition("/github/sync/tool", "使用宿主 GitHub 登录同步仓库"),
    HostCapability.GIT_REPOSITORY: HostCapabilityDefinition("/git/repository/tool", "当前项目的 Git 仓库操作"),
    HostCapability.GITHUB_REPOSITORIES: HostCapabilityDefinition("/github/platform/repositories", "GitHub 仓库管理"),
    HostCapability.GITHUB_PULL_REQUESTS: HostCapabilityDefinition("/github/platform/pull-requests", "GitHub PR 操作"),
    HostCapability.GITHUB_ISSUES: HostCapabilityDefinition("/github/platform/issues", "GitHub Issue 操作"),
    HostCapability.GITHUB_RELEASES: HostCapabilityDefinition("/github/platform/releases", "GitHub Release 和附件操作"),
    HostCapability.GITHUB_ACTIONS: HostCapabilityDefinition("/github/platform/actions", "GitHub Actions 操作"),
    HostCapability.MEMORY_MANAGEMENT: HostCapabilityDefinition("/memory/management/tool", "当前项目与全局记忆管理"),
    HostCapability.TOOL_CATALOG: HostCapabilityDefinition("/tools/capabilities/catalog", "读取本次调用允许的工具参数和示例"),
    HostCapability.RUN_STATUS: HostCapabilityDefinition("/tools/capabilities/run-status", "只读查询所属生成任务，或申请短期观察租约"),
}


def declared_host_capabilities(runtime: dict) -> tuple[HostCapability, ...]:
    value = runtime.get("host_capabilities", [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("runtime.host_capabilities 必须是能力名称数组。")
    runtime_type = runtime.get("type", "")
    if value and (not isinstance(runtime_type, str) or runtime_type.strip().lower() != "python"):
        raise ValueError("只有 Python 工具可以声明 runtime.host_capabilities。")
    try:
        return tuple(dict.fromkeys(HostCapability(item) for item in value))
    except ValueError as exc:
        raise ValueError(f"未知的后端能力声明：{exc}") from exc
