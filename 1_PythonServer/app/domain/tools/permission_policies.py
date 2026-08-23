from __future__ import annotations

from app.domain.tools.parameter_permissions import TOOL_PARAMETER_PERMISSION_TYPES

TOOL_PERMISSION_POLICY_VERSION = 1
TOOL_PERMISSION_DECISIONS = frozenset({"deny", "ask", "allow"})
TOOL_PERMISSION_FALLBACK = "ask"

_WORKSPACE_SCOPES = (
    "workspace_inside",
    "workspace_outside",
    "unresolved",
)
_NETWORK_SCOPES = (
    "loopback",
    "private_network",
    "public_network",
    "unresolved",
)
_TIANCE_DATA_SCOPES = (
    "current_project",
    "other_project",
    "global_data",
    "unresolved",
)
_PROGRAM_SCOPES = (
    "workspace_program",
    "system_program",
    "unresolved",
)
_ALL_SCOPES = ("all",)

TOOL_PERMISSION_POLICY_SCOPES: dict[str, tuple[str, ...]] = {
    "unknown": _ALL_SCOPES,
    "filesystem_read": _WORKSPACE_SCOPES,
    "filesystem_write": _WORKSPACE_SCOPES,
    "filesystem_delete": _WORKSPACE_SCOPES,
    "program_execute": _PROGRAM_SCOPES,
    "process_control": _ALL_SCOPES,
    "runtime_modify": _ALL_SCOPES,
    "network_access": _NETWORK_SCOPES,
    "credential_use": _ALL_SCOPES,
    "external_data_read": _ALL_SCOPES,
    "external_data_modify": _ALL_SCOPES,
    "tiance_data_read": _TIANCE_DATA_SCOPES,
    "tiance_data_write": _TIANCE_DATA_SCOPES,
    "tiance_data_delete": _TIANCE_DATA_SCOPES,
    "ui_control": _ALL_SCOPES,
}

TOOL_PERMISSION_POLICY_DEFAULTS: dict[str, dict[str, str]] = {
    "unknown": {"all": "ask"},
    "filesystem_read": {
        "workspace_inside": "allow",
        "workspace_outside": "allow",
        "unresolved": "allow",
    },
    "filesystem_write": {
        "workspace_inside": "allow",
        "workspace_outside": "ask",
        "unresolved": "ask",
    },
    "filesystem_delete": {
        "workspace_inside": "ask",
        "workspace_outside": "deny",
        "unresolved": "deny",
    },
    "program_execute": {
        "workspace_program": "allow",
        "system_program": "ask",
        "unresolved": "ask",
    },
    "process_control": {"all": "ask"},
    "runtime_modify": {"all": "ask"},
    "network_access": {
        "loopback": "allow",
        "private_network": "ask",
        "public_network": "allow",
        "unresolved": "ask",
    },
    "credential_use": {"all": "ask"},
    "external_data_read": {"all": "allow"},
    "external_data_modify": {"all": "ask"},
    "tiance_data_read": {
        "current_project": "allow",
        "other_project": "allow",
        "global_data": "allow",
        "unresolved": "allow",
    },
    "tiance_data_write": {
        "current_project": "allow",
        "other_project": "ask",
        "global_data": "ask",
        "unresolved": "ask",
    },
    "tiance_data_delete": {
        "current_project": "ask",
        "other_project": "ask",
        "global_data": "ask",
        "unresolved": "deny",
    },
    "ui_control": {"all": "allow"},
}

if set(TOOL_PERMISSION_POLICY_SCOPES) != (
    set(TOOL_PARAMETER_PERMISSION_TYPES) - {"none"}
) | {"unknown"}:
    raise RuntimeError("工具参数权限类型与权限策略定义不一致。")

if {
    permission_type: set(scopes)
    for permission_type, scopes in TOOL_PERMISSION_POLICY_DEFAULTS.items()
} != {
    permission_type: set(scopes)
    for permission_type, scopes in TOOL_PERMISSION_POLICY_SCOPES.items()
}:
    raise RuntimeError("工具权限默认策略与权限范围定义不一致。")


def build_default_tool_permission_policy() -> dict[str, object]:
    return {
        "version": TOOL_PERMISSION_POLICY_VERSION,
        "fallback": TOOL_PERMISSION_FALLBACK,
        "policies": {
            permission_type: dict(TOOL_PERMISSION_POLICY_DEFAULTS[permission_type])
            for permission_type in TOOL_PERMISSION_POLICY_SCOPES
        },
    }


def normalize_tool_permission_policy(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("permissions.json 必须是 JSON 对象。")

    version = payload.get("version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != TOOL_PERMISSION_POLICY_VERSION
    ):
        raise ValueError(
            f"permissions.json.version 必须为 {TOOL_PERMISSION_POLICY_VERSION}。"
        )

    fallback = payload.get("fallback")
    if not isinstance(fallback, str) or fallback not in TOOL_PERMISSION_DECISIONS:
        raise ValueError("permissions.json.fallback 必须是 deny、ask 或 allow。")

    raw_policies = payload.get("policies")
    if not isinstance(raw_policies, dict):
        raise ValueError("permissions.json.policies 必须是 JSON 对象。")

    unknown_permission_types = set(raw_policies) - set(TOOL_PERMISSION_POLICY_SCOPES)
    if unknown_permission_types:
        names = "、".join(sorted(str(item) for item in unknown_permission_types))
        raise ValueError(f"permissions.json 包含未知权限点：{names}。")

    policies: dict[str, dict[str, str]] = {}
    for permission_type, scopes in TOOL_PERMISSION_POLICY_SCOPES.items():
        raw_policy = raw_policies.get(permission_type, {})
        if not isinstance(raw_policy, dict):
            raise ValueError(f"权限点 {permission_type} 的配置必须是 JSON 对象。")

        unknown_scopes = set(raw_policy) - set(scopes)
        if unknown_scopes:
            names = "、".join(sorted(str(item) for item in unknown_scopes))
            raise ValueError(f"权限点 {permission_type} 包含未知范围：{names}。")

        normalized_scopes: dict[str, str] = {}
        for scope in scopes:
            decision = raw_policy.get(scope, fallback)
            if not isinstance(decision, str) or decision not in TOOL_PERMISSION_DECISIONS:
                raise ValueError(
                    f"权限点 {permission_type} 的 {scope} 必须是 deny、ask 或 allow。"
                )
            normalized_scopes[scope] = decision
        policies[permission_type] = normalized_scopes

    return {
        "version": TOOL_PERMISSION_POLICY_VERSION,
        "fallback": fallback,
        "policies": policies,
    }
