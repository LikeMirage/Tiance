from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from app.core.errors import BadRequestError
from app.domain.tools import ToolDependency

_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9_,.\-\s]+\])?"
    r"(?P<specifier>.*)$"
)
_SPECIFIER_RE = re.compile(r"^(==|!=|>=|<=|~=|>|<)\s*([^,\s]+)$")


@dataclass(frozen=True, slots=True)
class ParsedRequirement:
    line_number: int
    requirement: str
    name: str
    specifier: str
    invalid_message: str | None = None


def parse_requirements_file(requirements_path: Path) -> tuple[ParsedRequirement, ...]:
    if not requirements_path.is_file():
        return ()

    parsed: list[ParsedRequirement] = []
    for line_number, raw_line in enumerate(
        requirements_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = _strip_requirement_comment(raw_line).strip()
        if not line:
            continue
        parsed.append(_parse_requirement_line(line_number, line))
    return tuple(parsed)


def resolve_dependency_status(
    requirement: ParsedRequirement,
    installed_versions: dict[str, str],
) -> ToolDependency:
    if requirement.invalid_message is not None:
        return ToolDependency(
            line_number=requirement.line_number,
            requirement=requirement.requirement,
            name=requirement.name,
            specifier=requirement.specifier,
            installed_version=None,
            status="invalid",
            message=requirement.invalid_message,
        )

    installed_version = installed_versions.get(normalize_package_name(requirement.name))
    if installed_version is None:
        return ToolDependency(
            line_number=requirement.line_number,
            requirement=requirement.requirement,
            name=requirement.name,
            specifier=requirement.specifier,
            installed_version=None,
            status="missing",
            message="未安装。",
        )

    if requirement.specifier and not _matches_specifier(installed_version, requirement.specifier):
        return ToolDependency(
            line_number=requirement.line_number,
            requirement=requirement.requirement,
            name=requirement.name,
            specifier=requirement.specifier,
            installed_version=installed_version,
            status="version_mismatch",
            message="已安装版本不符合要求。",
        )

    return ToolDependency(
        line_number=requirement.line_number,
        requirement=requirement.requirement,
        name=requirement.name,
        specifier=requirement.specifier,
        installed_version=installed_version,
        status="installed",
        message="已安装。",
    )


def select_install_targets(
    dependencies: tuple[ToolDependency, ...],
    *,
    requirement: str | None,
) -> tuple[ToolDependency, ...]:
    candidates = [
        dependency
        for dependency in dependencies
        if dependency.status in {"missing", "version_mismatch"}
    ]
    if requirement is None or not requirement.strip():
        return tuple(candidates)

    wanted = requirement.strip()
    wanted_name = normalize_package_name(wanted)
    for dependency in dependencies:
        if dependency.requirement == wanted or normalize_package_name(dependency.name) == wanted_name:
            if dependency.status == "invalid":
                raise BadRequestError("依赖格式无效，不能安装。")
            if dependency.status == "installed":
                return ()
            return (dependency,)
    raise BadRequestError("只能安装当前 requirements.txt 中声明的依赖。")


def select_uninstall_target(
    dependencies: tuple[ToolDependency, ...],
    *,
    requirement: str,
) -> ToolDependency:
    wanted = requirement.strip()
    if not wanted:
        raise BadRequestError("必须指定要卸载的依赖。")
    wanted_name = normalize_package_name(wanted)
    for dependency in dependencies:
        if dependency.requirement == wanted or normalize_package_name(dependency.name) == wanted_name:
            if dependency.status == "invalid":
                raise BadRequestError("依赖格式无效，不能卸载。")
            if dependency.status == "missing":
                raise BadRequestError("依赖尚未安装。")
            return dependency
    raise BadRequestError("只能卸载当前 requirements.txt 中声明的依赖。")


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement_line(line_number: int, line: str) -> ParsedRequirement:
    if line.startswith("-") or "://" in line or "@" in line or ";" in line:
        return _invalid_requirement(line_number, line, "当前只支持普通包名和版本范围。")

    match = _REQUIREMENT_RE.match(line)
    if match is None:
        return _invalid_requirement(line_number, line, "依赖格式无效。")

    name = match.group("name")
    extras = (match.group("extras") or "").replace(" ", "")
    specifier = _compact_specifier(match.group("specifier") or "")
    if not _PACKAGE_NAME_RE.match(name):
        return _invalid_requirement(line_number, line, "依赖包名无效。")
    if specifier and not _is_supported_specifier(specifier):
        return _invalid_requirement(line_number, line, "版本范围格式无效。")

    return ParsedRequirement(
        line_number=line_number,
        requirement=f"{name}{extras}{specifier}",
        name=name,
        specifier=specifier,
    )


def _invalid_requirement(line_number: int, line: str, message: str) -> ParsedRequirement:
    return ParsedRequirement(
        line_number=line_number,
        requirement=line,
        name="",
        specifier="",
        invalid_message=message,
    )


def _strip_requirement_comment(raw_line: str) -> str:
    return re.sub(r"\s+#.*$", "", raw_line)


def _compact_specifier(raw_specifier: str) -> str:
    return re.sub(r"\s+", "", raw_specifier.strip())


def _is_supported_specifier(specifier: str) -> bool:
    return all(_SPECIFIER_RE.match(part) is not None for part in specifier.split(","))


def _matches_specifier(version: str, specifier: str) -> bool:
    for part in specifier.split(","):
        match = _SPECIFIER_RE.match(part)
        if match is None:
            return True
        operator, expected = match.groups()
        comparison = _compare_versions(version, expected)
        if operator == "==" and comparison != 0:
            return False
        if operator == "!=" and comparison == 0:
            return False
        if operator == ">=" and comparison < 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
        if operator == "~=" and comparison < 0:
            return False
    return True


def _compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    max_len = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_len - len(left_parts)))
    right_parts.extend([0] * (max_len - len(right_parts)))
    if left_parts == right_parts:
        return 0
    return 1 if left_parts > right_parts else -1


def _version_parts(version: str) -> list[int]:
    return [int(part) for part in re.findall(r"\d+", version)]
