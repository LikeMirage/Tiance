from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


OPERATIONS = {
    "check",
    "install",
    "install_requirements",
    "list",
    "repair",
    "show",
    "uninstall",
}
DEFAULT_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9_,.\-\s]+\])?"
    r"(?P<specifier>.*)$"
)
_SPECIFIER_RE = re.compile(r"^(==|!=|>=|<=|~=|>|<)\s*([^,\s]+)$")


class InputError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class PackageRequest:
    operation: str
    packages: tuple[str, ...]
    target_path: str | None
    target_tool: str | None
    index_url: str
    timeout_seconds: int


def parse_request(payload: dict[str, Any]) -> PackageRequest:
    operation = str(payload.get("operation") or "").strip().lower()
    if operation not in OPERATIONS:
        raise InputError(
            "INVALID_OPERATION",
            "operation 必须是 check、install、install_requirements、list、repair、show 或 uninstall。",
            {"operation": payload.get("operation")},
        )
    packages = _read_packages(payload.get("packages"), operation=operation)
    target_tool, target_path = _read_target(
        payload.get("target_tool"),
        payload.get("target_path"),
    )
    if operation == "install_requirements" and target_path is not None:
        raise InputError(
            "TOOL_TARGET_REQUIRED",
            "install_requirements 只能用于工具目标。",
        )
    index_url = _read_index_url(payload.get("index_url"), operation=operation)
    timeout_seconds = _read_timeout(payload.get("timeout_seconds"))
    return PackageRequest(
        operation=operation,
        packages=packages,
        target_path=target_path,
        target_tool=target_tool,
        index_url=index_url,
        timeout_seconds=timeout_seconds,
    )


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    match = _REQUIREMENT_RE.fullmatch(requirement)
    return match.group("name") if match is not None else requirement


def _read_packages(value: Any, *, operation: str) -> tuple[str, ...]:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, list):
        items = value
    else:
        raise InputError("INVALID_PACKAGES", "packages 必须是字符串数组。")

    if operation in {"check", "install_requirements", "list", "repair"}:
        if items:
            raise InputError(
                "PACKAGES_NOT_ALLOWED",
                f"{operation} 操作不接收 packages。",
            )
        return ()
    if not 1 <= len(items) <= 20:
        raise InputError("PACKAGES_REQUIRED", f"{operation} 操作需要 1-20 个包。")

    packages: list[str] = []
    seen_names: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise InputError(
                "INVALID_PACKAGE",
                "packages 必须全部是字符串。",
                {"index": index},
            )
        package = item.strip()
        if not package or len(package) > 200:
            raise InputError("INVALID_PACKAGE", "包名长度必须在 1-200 个字符之间。", {"index": index})
        parsed = _parse_requirement(package) if operation == "install" else _parse_package_name(package)
        normalized_name = normalize_package_name(requirement_name(parsed))
        if normalized_name in seen_names:
            raise InputError("DUPLICATE_PACKAGE", f"包 '{requirement_name(parsed)}' 重复出现。")
        seen_names.add(normalized_name)
        packages.append(parsed)
    return tuple(packages)


def _parse_requirement(value: str) -> str:
    if value.startswith("-") or "://" in value or "@" in value or ";" in value:
        raise InputError("UNSUPPORTED_REQUIREMENT", "只支持 PyPI 普通包名和版本范围。", {"requirement": value})
    match = _REQUIREMENT_RE.fullmatch(value)
    if match is None:
        raise InputError("INVALID_REQUIREMENT", "依赖格式无效。", {"requirement": value})
    name = match.group("name")
    extras = (match.group("extras") or "").replace(" ", "")
    specifier = re.sub(r"\s+", "", (match.group("specifier") or "").strip())
    if not _PACKAGE_NAME_RE.fullmatch(name):
        raise InputError("INVALID_REQUIREMENT", "依赖包名无效。", {"requirement": value})
    if specifier and not all(_SPECIFIER_RE.fullmatch(part) for part in specifier.split(",")):
        raise InputError("INVALID_REQUIREMENT", "版本范围格式无效。", {"requirement": value})
    return f"{name}{extras}{specifier}"


def _parse_package_name(value: str) -> str:
    if not _PACKAGE_NAME_RE.fullmatch(value):
        raise InputError("INVALID_PACKAGE_NAME", "show 和 uninstall 只接收普通包名。", {"package": value})
    return value


def _read_index_url(value: Any, *, operation: str) -> str:
    if operation not in {"install", "install_requirements"}:
        if value not in {None, ""}:
            raise InputError("INDEX_URL_NOT_ALLOWED", f"{operation} 操作不接收 index_url。")
        return DEFAULT_INDEX_URL
    index_url = str(value or DEFAULT_INDEX_URL).strip()
    parsed = urlsplit(index_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputError("INVALID_INDEX_URL", "index_url 必须是 http/https 地址。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise InputError("UNSAFE_INDEX_URL", "index_url 不能包含凭证、查询参数或片段。")
    return index_url


def parse_install_requirement(value: str) -> str:
    return _parse_requirement(value.strip())


def _read_target(tool_value: Any, path_value: Any) -> tuple[str | None, str | None]:
    target_tool = _read_optional_target_text(tool_value, field_name="target_tool")
    target_path = _read_optional_target_text(path_value, field_name="target_path")
    if target_tool is not None and target_path is not None:
        raise InputError(
            "AMBIGUOUS_TARGET",
            "target_tool 和 target_path 不能同时填写。",
        )
    return target_tool, target_path


def _read_optional_target_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError("INVALID_TARGET", f"{field_name} 必须是字符串。")
    normalized = value.strip()
    if not normalized or len(normalized) > 500 or "\x00" in normalized:
        raise InputError(
            "INVALID_TARGET",
            f"{field_name} 长度必须在 1-500 个字符之间。",
        )
    return normalized


def _read_timeout(value: Any) -> int:
    if value is None:
        return 300
    if isinstance(value, bool):
        raise InputError("INVALID_TIMEOUT", "timeout_seconds 必须是整数。")
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise InputError("INVALID_TIMEOUT", "timeout_seconds 必须是整数。") from exc
    if not 10 <= timeout <= 600:
        raise InputError("INVALID_TIMEOUT", "timeout_seconds 必须在 10-600 之间。")
    return timeout
