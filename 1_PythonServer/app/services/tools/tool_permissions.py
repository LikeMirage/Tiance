from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from json import load
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.domain.tools.parameter_permissions import (
    TOOL_PARAMETER_PERMISSION_TYPE_KEY,
    TOOL_PARAMETER_PERMISSION_TYPES,
)
from app.domain.tools.permission_policies import (
    build_default_tool_permission_policy,
    normalize_tool_permission_policy,
)
from app.infra.tools.tool_project_config_constants import TOOL_PERMISSIONS_FILE


_DECISION_PRIORITY = {"allow": 0, "ask": 1, "deny": 2}
_FILESYSTEM_PERMISSION_TYPES = {
    "filesystem_read",
    "filesystem_write",
    "filesystem_delete",
}
_TIANCE_DATA_PERMISSION_TYPES = {
    "tiance_data_read",
    "tiance_data_write",
    "tiance_data_delete",
}


@dataclass(frozen=True, slots=True)
class ToolPermissionFact:
    tool_name: str
    parameter_name: str
    permission_type: str
    scope: str
    decision: str


@dataclass(frozen=True, slots=True)
class ToolPermissionEvaluation:
    decision: str
    facts: tuple[ToolPermissionFact, ...]


def evaluate_tool_permissions(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    input_schema: dict[str, Any],
    tool_root: str,
    workspace_root: str | None,
    project_id: str | None,
) -> ToolPermissionEvaluation:
    policy = _load_policy(Path(tool_root))
    properties = input_schema.get("properties")
    property_schemas = properties if isinstance(properties, dict) else {}
    facts: list[ToolPermissionFact] = []

    for parameter_name, value in arguments.items():
        parameter_schema = property_schemas.get(parameter_name)
        if not isinstance(parameter_schema, dict):
            permission_type = "unknown"
        else:
            raw_permission_type = parameter_schema.get(TOOL_PARAMETER_PERMISSION_TYPE_KEY)
            permission_type = (
                raw_permission_type
                if isinstance(raw_permission_type, str)
                and raw_permission_type in TOOL_PARAMETER_PERMISSION_TYPES
                else "unknown"
            )
        if permission_type == "none":
            continue

        for scope in _resolve_scopes(
            permission_type,
            value,
            workspace_root=workspace_root,
            project_id=project_id,
        ):
            decision = _read_decision(policy, permission_type, scope)
            facts.append(
                ToolPermissionFact(
                    tool_name=tool_name,
                    parameter_name=str(parameter_name),
                    permission_type=permission_type,
                    scope=scope,
                    decision=decision,
                )
            )

    decision = max(
        (fact.decision for fact in facts),
        key=lambda item: _DECISION_PRIORITY[item],
        default="allow",
    )
    return ToolPermissionEvaluation(decision=decision, facts=tuple(facts))


def combine_tool_permission_evaluations(
    evaluations: tuple[ToolPermissionEvaluation, ...],
) -> ToolPermissionEvaluation:
    facts = tuple(fact for evaluation in evaluations for fact in evaluation.facts)
    return ToolPermissionEvaluation(
        decision=max(
            (evaluation.decision for evaluation in evaluations),
            key=lambda item: _DECISION_PRIORITY[item],
            default="allow",
        ),
        facts=facts,
    )


def _load_policy(tool_root: Path) -> dict[str, object]:
    path = tool_root / TOOL_PERMISSIONS_FILE
    try:
        with path.open("r", encoding="utf-8") as file:
            return normalize_tool_permission_policy(load(file))
    except (OSError, ValueError, TypeError):
        # A missing or damaged policy must never silently make a tool less restricted.
        return build_default_tool_permission_policy()


def _read_decision(
    policy: dict[str, object],
    permission_type: str,
    scope: str,
) -> str:
    fallback = policy.get("fallback")
    normalized_fallback = fallback if fallback in _DECISION_PRIORITY else "ask"
    policies = policy.get("policies")
    if not isinstance(policies, dict):
        return normalized_fallback
    permission_policy = policies.get(permission_type)
    if not isinstance(permission_policy, dict):
        return normalized_fallback
    decision = permission_policy.get(scope)
    return decision if decision in _DECISION_PRIORITY else normalized_fallback


def _resolve_scopes(
    permission_type: str,
    value: Any,
    *,
    workspace_root: str | None,
    project_id: str | None,
) -> tuple[str, ...]:
    if permission_type in _FILESYSTEM_PERMISSION_TYPES:
        return _filesystem_scopes(value, workspace_root)
    if permission_type == "program_execute":
        return _program_scopes(value, workspace_root)
    if permission_type == "network_access":
        return _network_scopes(value)
    if permission_type in _TIANCE_DATA_PERMISSION_TYPES:
        return _tiance_data_scopes(value, project_id)
    return ("all",)


def _leaf_values(value: Any) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return tuple(leaf for item in value.values() for leaf in _leaf_values(item))
    if isinstance(value, (list, tuple)):
        return tuple(leaf for item in value for leaf in _leaf_values(item))
    return (value,)


def _filesystem_scopes(value: Any, workspace_root: str | None) -> tuple[str, ...]:
    scopes: set[str] = set()
    workspace = Path(workspace_root).resolve(strict=False) if workspace_root else None
    for leaf in _leaf_values(value):
        if not isinstance(leaf, str) or not leaf.strip() or workspace is None:
            scopes.add("unresolved")
            continue
        try:
            candidate = Path(leaf.strip()).expanduser()
            resolved = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else (workspace / candidate).resolve(strict=False)
            )
            scopes.add(
                "workspace_inside"
                if resolved == workspace or workspace in resolved.parents
                else "workspace_outside"
            )
        except (OSError, ValueError):
            scopes.add("unresolved")
    return tuple(sorted(scopes)) or ("unresolved",)


def _program_scopes(value: Any, workspace_root: str | None) -> tuple[str, ...]:
    scopes: set[str] = set()
    workspace = Path(workspace_root).resolve(strict=False) if workspace_root else None
    for leaf in _leaf_values(value):
        if not isinstance(leaf, str) or not leaf.strip():
            scopes.add("unresolved")
            continue
        executable = leaf.strip().split()[0]
        path = Path(executable)
        if not path.is_absolute() and path.parent == Path("."):
            scopes.add("system_program")
            continue
        if workspace is None:
            scopes.add("unresolved")
            continue
        try:
            resolved = (
                path.resolve(strict=False)
                if path.is_absolute()
                else (workspace / path).resolve(strict=False)
            )
            scopes.add(
                "workspace_program"
                if resolved == workspace or workspace in resolved.parents
                else "system_program"
            )
        except (OSError, ValueError):
            scopes.add("unresolved")
    return tuple(sorted(scopes)) or ("unresolved",)


def _network_scopes(value: Any) -> tuple[str, ...]:
    scopes: set[str] = set()
    for leaf in _leaf_values(value):
        if not isinstance(leaf, str) or not leaf.strip():
            scopes.add("unresolved")
            continue
        raw = leaf.strip()
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = (parsed.hostname or "").strip().casefold()
        if not host:
            scopes.add("unresolved")
            continue
        if host == "localhost":
            scopes.add("loopback")
            continue
        try:
            address = ip_address(host)
        except ValueError:
            scopes.add("public_network")
            continue
        if address.is_loopback:
            scopes.add("loopback")
        elif address.is_private or address.is_link_local:
            scopes.add("private_network")
        else:
            scopes.add("public_network")
    return tuple(sorted(scopes)) or ("unresolved",)


def _tiance_data_scopes(value: Any, project_id: str | None) -> tuple[str, ...]:
    scopes: set[str] = set()
    normalized_project_id = (project_id or "").strip()
    for leaf in _leaf_values(value):
        if isinstance(leaf, str) and normalized_project_id and leaf.strip() == normalized_project_id:
            scopes.add("current_project")
        else:
            scopes.add("unresolved")
    return tuple(sorted(scopes)) or ("unresolved",)
