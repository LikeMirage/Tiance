"""Theme workspace lifecycle; the host owns collection/path validation."""
import json
import os
from pathlib import Path

from app.domain.file_workspace import TextFileUpdate
from app.domain.project import ProjectKind
from app.services.application.project_scaffold import require_collection_workspace, install_project_scaffold
from app.services.application.theme_project_policy import ensure_theme_project_can_be_deleted
from app.services.project import get_project_service
from app.schemas.themes import ThemePackageDefinition


def initialize_current_theme(tool_root: Path) -> dict:
    project_id = os.environ.get("TIANCE_PROJECT_ID", "")
    workspace = os.environ.get("TIANCE_WORKSPACE_ROOT", "")
    if not project_id or not workspace:
        raise ValueError("缺少调用工作区上下文，不能初始化主题。")
    project = require_collection_workspace(project_id, "theme", workspace)
    payload = json.loads((tool_root / "assets/theme_backups/light.json").read_text("utf-8"))
    # Theme package IDs follow the directory name, while the project catalog
    # can have an independent UUID (for example imported marketplace themes).
    payload.update(id=Path(project.root_path).name, registrationName=project.name)
    ThemePackageDefinition.model_validate(payload)
    documentation = "docs/theme-development/README.md"
    result = install_project_scaffold(project_id, "theme", [
        TextFileUpdate("theme.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n"),
        TextFileUpdate(documentation, (tool_root / "assets/documentation/README.md").read_text("utf-8")),
    ], workspace)
    actual = json.loads((Path(workspace) / "theme.json").read_text("utf-8"))
    return {**result, "action": "initialize_current", "theme_id": actual.get("id"),
            "documentation_path": str(Path(workspace) / documentation), "activated": False,
            "guidance": "仅补缺失内容，已有主题配置不覆盖。先读取制作说明，再设计；不会自动切换主题。"}


def delete_theme_project(package_path: Path) -> str:
    service = get_project_service()
    project = next((p for p in service.list_projects()
                    if p.project_kind is ProjectKind.THEME
                    and Path(p.root_path).resolve() == package_path.resolve()), None)
    if project is None:
        raise ValueError("主题没有登记为项目，请刷新主题列表后重试。")
    if project.project_id == os.environ.get("TIANCE_PROJECT_ID"):
        raise ValueError("不能删除本次调用所在的主题项目。")
    ensure_theme_project_can_be_deleted(project)
    service.delete_project(project.project_id)
    return project.project_id
