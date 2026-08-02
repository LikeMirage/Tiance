from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from json import dumps, loads
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from app.core.atomic_replace import atomic_replace_path


PROJECT_IDENTITY_RELATIVE_PATH = Path(".Tiance") / "project.json"
PROJECT_IDENTITY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    project_id: str
    name: str


def read_project_identity(project_root: str | Path) -> ProjectIdentity | None:
    identity_path = Path(project_root).resolve() / PROJECT_IDENTITY_RELATIVE_PATH
    if not identity_path.is_file():
        return None
    try:
        payload = loads(identity_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("项目身份文件不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise ValueError("项目身份文件必须是 JSON 对象。")
    if payload.get("schema_version") != PROJECT_IDENTITY_SCHEMA_VERSION:
        raise ValueError("项目身份文件版本不受支持。")
    return ProjectIdentity(
        project_id=_normalize_project_id(payload.get("project_id")),
        name=_required_name(payload.get("name")),
    )


def write_project_identity(
    project_root: str | Path,
    identity: ProjectIdentity,
) -> bool:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError("项目文件夹不存在。")
    normalized = ProjectIdentity(
        project_id=_normalize_project_id(identity.project_id),
        name=_required_name(identity.name),
    )
    identity_path = root / PROJECT_IDENTITY_RELATIVE_PATH
    payload = {
        "schema_version": PROJECT_IDENTITY_SCHEMA_VERSION,
        "project_id": normalized.project_id,
        "name": normalized.name,
    }
    text = dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if identity_path.is_file():
        try:
            if identity_path.read_text(encoding="utf-8-sig") == text:
                return False
        except (OSError, UnicodeError):
            pass

    identity_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=identity_path.parent,
            delete=False,
            prefix=".project.",
            suffix=".tmp",
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
        atomic_replace_path(temporary_path, identity_path)
    except Exception:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()
        raise
    return True


def _normalize_project_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("项目身份 project_id 必须是 UUID。")
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise ValueError("项目身份 project_id 必须是 UUID。") from exc


def _required_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("项目身份 name 必须是非空字符串。")
    return value.strip()
