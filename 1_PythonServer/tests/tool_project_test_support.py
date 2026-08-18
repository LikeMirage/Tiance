from __future__ import annotations

from datetime import UTC, datetime
from json import dumps
from pathlib import Path
import shutil
from uuid import uuid4

from app.domain.project import Project, ProjectKind
from app.domain.tools import ToolFolder, Toolset
from app.infra.tools.tool_project_config_constants import (
    TOOL_ASSETS_DIR,
    TOOL_DEFAULT_ENTRY_FILE,
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
    TOOL_REQUIREMENTS_FILE,
)


class ToolProjectFixture:
    """测试用扁平工具项目目录，不模拟旧 toolset/folders 结构。"""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self._toolsets: list[Toolset] = []
        self._folders: list[ToolFolder] = []

    def create_toolset(self, *, name: str | None) -> Toolset:
        now = _now()
        toolset = Toolset(
            category_id=f"tool_category_{uuid4().hex}",
            name=(name or "新建分类").strip(),
            scope="local",
            root_path=str(self.root_path),
            readonly=False,
            created_at=now,
            updated_at=now,
        )
        self._toolsets.append(toolset)
        return toolset

    def create_tool_folder(self, category_id: str, *, name: str | None) -> ToolFolder:
        now = _now()
        project_id = str(uuid4())
        display_name = (name or "新建工具").strip()
        project_root = self.root_path / project_id
        _write_tool_files(
            project_root,
            project_id=project_id,
            display_name=display_name,
            now=now,
        )
        folder = ToolFolder(
            project_id=project_id,
            category_id=category_id,
            name=display_name,
            root_path=str(project_root),
            created_at=now,
            updated_at=now,
        )
        self._folders.append(folder)
        return folder

    def list_toolsets(self) -> tuple[Toolset, ...]:
        return tuple(self._toolsets)

    def list_tool_folders(self, category_id: str) -> tuple[ToolFolder, ...]:
        return tuple(item for item in self._folders if item.category_id == category_id)

    def get_tool_folder(self, category_id: str, project_id: str) -> ToolFolder:
        return next(
            item
            for item in self._folders
            if item.category_id == category_id and item.project_id == project_id
        )

    def require_tool_project(self, category_id: str, project_id: str) -> Project:
        folder = self.get_tool_folder(category_id, project_id)
        return Project(
            project_id=folder.project_id,
            name=folder.name,
            root_path=folder.root_path,
            category_id=folder.category_id,
            project_kind=ProjectKind.TOOL,
            is_default=False,
            sort_order=self._folders.index(folder),
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )

    def folder_for_project(self, project: Project) -> ToolFolder:
        return self.get_tool_folder(project.category_id, project.project_id)

    def rename_tool_folder(
        self,
        category_id: str,
        project_id: str,
        *,
        name: str,
    ) -> ToolFolder:
        current = self.get_tool_folder(category_id, project_id)
        updated = ToolFolder(
            project_id=current.project_id,
            category_id=current.category_id,
            name=name,
            root_path=current.root_path,
            created_at=current.created_at,
            updated_at=_now(),
        )
        self._folders[self._folders.index(current)] = updated
        return updated

    def delete_tool_folder(self, category_id: str, project_id: str) -> None:
        current = self.get_tool_folder(category_id, project_id)
        self._folders.remove(current)
        root = Path(current.root_path)
        if root.is_dir():
            shutil.rmtree(root)


def _write_tool_files(
    root: Path,
    *,
    project_id: str,
    display_name: str,
    now: str,
) -> None:
    manifest = {
        "name": f"custom_tool_{project_id.replace('-', '_')}",
        "registration_name": display_name,
        "description": "",
        "keywords": [],
        "loading": {"dynamic": True},
        "execution": {"parallel": True},
        "files": {
            "input_schema": TOOL_INPUT_SCHEMA_FILE,
            "output_schema": TOOL_OUTPUT_SCHEMA_FILE,
            "examples": TOOL_EXAMPLES_FILE,
        },
        "runtime": {"type": "python", "entry": TOOL_DEFAULT_ENTRY_FILE, "timeout_seconds": 60},
        "io": {"input": "stdin_json", "output": "stdout_json"},
        "state": {"enabled": True},
    }
    _write_json(root / TOOL_FOLDER_MANIFEST_FILE, manifest)
    _write_json(root / TOOL_INPUT_SCHEMA_FILE, {"type": "object", "properties": {}})
    _write_json(root / TOOL_OUTPUT_SCHEMA_FILE, {"type": "object", "properties": {}})
    _write_json(root / TOOL_EXAMPLES_FILE, [])
    (root / TOOL_DEFAULT_ENTRY_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / TOOL_DEFAULT_ENTRY_FILE).write_text("", encoding="utf-8")
    (root / TOOL_REQUIREMENTS_FILE).write_text("", encoding="utf-8")
    (root / TOOL_ASSETS_DIR).mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()
