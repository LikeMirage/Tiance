"""Public host capability contract shared by tool config, SDK and gateway.

This registry describes capabilities, never individual tool names. Routes still
authenticate every request; registering a path does not implement its handler.
"""
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from app.domain.llm.provider_catalog import AuthScheme, ProviderProtocolFamily


class HostCapability(StrEnum):
    SESSION_MODEL = "session_model"
    PROVIDER_AUTH = "provider_auth"
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
    HostCapability.SESSION_MODEL: HostCapabilityDefinition("/llm/provider-capabilities/session-model", "读取调用会话的模型来源，向绑定模型提交已鉴权的请求"),
    HostCapability.PROVIDER_AUTH: HostCapabilityDefinition("/llm/provider-capabilities/authenticated-post", "使用供应商凭据向工具声明的同源接口提交 JSON"),
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
    declared_provider_endpoints(runtime)
    declared_session_model_endpoints(runtime)
    try:
        return tuple(dict.fromkeys(HostCapability(item) for item in value))
    except ValueError as exc:
        raise ValueError(f"未知的后端能力声明：{exc}") from exc


@dataclass(frozen=True, slots=True)
class ProviderEndpointGrant:
    name: str
    provider_id: str
    url: str
    auth_scheme: AuthScheme | None = None


@dataclass(frozen=True, slots=True)
class SessionModelEndpoint:
    name: str
    url: str
    protocol: ProviderProtocolFamily


def declared_session_model_endpoints(runtime: dict) -> tuple[SessionModelEndpoint, ...]:
    entries = runtime.get("session_model_endpoints", {})
    if not isinstance(entries, dict):
        raise ValueError("runtime.session_model_endpoints 必须是按名称声明的接口对象。")
    if entries and HostCapability.SESSION_MODEL not in runtime.get("host_capabilities", []):
        raise ValueError("声明会话模型端点需要 session_model 能力。")
    result = []
    for name, item in entries.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(item, dict):
            raise ValueError("会话模型端点须按名称声明。")
        url = item.get("url")
        if not isinstance(url, str) or not url or any(c.isspace() for c in url) or "\\" in url:
            raise ValueError("会话模型端点须声明有效地址。")
        parsed = urlsplit(url)
        if (parsed.scheme and (parsed.scheme != "https" or not parsed.hostname)
                or url.startswith("//") or parsed.username is not None or parsed.query or parsed.fragment):
            raise ValueError("会话模型端点须使用固定 HTTPS 地址或同源相对路径。")
        _ = parsed.port
        result.append(SessionModelEndpoint(name, url, ProviderProtocolFamily(item.get("protocol"))))
    return tuple(result)


def declared_provider_endpoints(runtime: dict) -> tuple[ProviderEndpointGrant, ...]:
    entries = runtime.get("provider_endpoints", {})
    if not isinstance(entries, dict):
        raise ValueError("runtime.provider_endpoints 必须是按名称声明的接口对象。")
    if entries and HostCapability.PROVIDER_AUTH not in runtime.get("host_capabilities", []):
        raise ValueError("声明供应商地址需要 provider_auth 能力。")
    endpoints = []
    for name, entry in entries.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("供应商接口名称不能为空。")
        if not isinstance(entry, dict) or not {"provider_id", "url"} <= set(entry) <= {"provider_id", "url", "auth_scheme"}:
            raise ValueError("供应商地址须声明 provider_id 与 url。")
        provider_id, url = entry["provider_id"], entry["url"]
        if not isinstance(provider_id, str) or not provider_id.strip() or not isinstance(url, str):
            raise ValueError("供应商地址声明无效。")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or not parsed.path
                or any(c.isspace() for c in url) or "\\" in url):
            raise ValueError("供应商地址须为固定的 HTTPS 接口地址。")
        _ = parsed.port  # Reject invalid port numbers during manifest validation.
        scheme = AuthScheme(entry["auth_scheme"]) if "auth_scheme" in entry else None
        endpoints.append(ProviderEndpointGrant(name, provider_id, url, scheme))
    return tuple(endpoints)
